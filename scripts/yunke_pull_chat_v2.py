#!/usr/bin/env python3
"""
yunke_pull_chat_v2.py — 云客聊天记录增量拉取（纯allRecords模式）

设计要点：
- 纯allRecords，私聊+群聊全覆盖，不用records接口
- 指数跳跃空窗口（1h→2h→4h→24h→72h），命中数据后回落到1h
- 精确sleep（用elapsed计算，不浪费时间）
- 断点续传（状态文件存游标timestamp）
- 批量upsert 100条/批
- 启动时可查DB跳过已覆盖区间

用法：
  cron每小时:  python3 yunke_pull_chat_v2.py
  全量回补:    python3 yunke_pull_chat_v2.py --backfill --start 2024-09-01
  从断点续传:  python3 yunke_pull_chat_v2.py --backfill --resume
"""

import hashlib
import time
import json
import os
import sys
import logging
import argparse
from datetime import datetime, timezone, timedelta

import requests
from supabase import create_client

# ============================================================
# 配置
# ============================================================

COMPANY = "5fri8k"
SIGN_KEY = "F446226EBF084CF6AAC00E"
PARTNER_ID = "pDB33ABE148934DD081FD7D4C80654195"
API_BASE = "https://phone.yunkecn.com"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://dieeejjzbhkpgxdhwlxf.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

# 状态文件路径
STATE_DIR = os.path.dirname(os.path.abspath(__file__))
CURSOR_FILE = os.path.join(STATE_DIR, ".pull_chat_cursor")  # 增量模式游标
BACKFILL_FILE = os.path.join(STATE_DIR, ".backfill_cursor")  # 回补模式游标

# API限频：5秒/次，我们用5.5秒留余量
MIN_INTERVAL = 5.5
# 限流重试
MAX_RETRIES = 3
RETRY_SLEEP = 60

# 批量upsert大小
BATCH_SIZE = 100

# 指数跳跃步长序列（小时）
SKIP_STEPS = [1, 2, 4, 24, 72]

# allRecords要求timestamp < 当前时间30分钟
LAG_MINUTES = 35  # 多留5分钟余量

# 销售微信号映射
SALES_MAP = {
    "wxid_am3kdib9tt3722": {"name": "可欣", "email": "kexin@test.com"},
    "wxid_p03xoj66oss112": {"name": "小杰", "email": "xiaojie@test.com"},
    "wxid_cbk7hkyyp11t12": {"name": "霄剑", "email": "xiaojian@test.com"},
    "wxid_aufah51bw9ok22": {"name": "Fiona", "email": None},
    "wxid_idjldooyihpj22": {"name": "晴天喵", "email": None},
    "wxid_rxc39paqvic522": {"name": "Joy", "email": None},
}
SALES_WECHAT_IDS = set(SALES_MAP.keys())

# ============================================================
# 日志
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ============================================================
# Supabase客户端
# ============================================================

_sb = None

def get_sb():
    global _sb
    if _sb is None:
        if not SUPABASE_KEY:
            log.error("SUPABASE_SERVICE_ROLE_KEY 环境变量未设置")
            sys.exit(1)
        _sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _sb

# ============================================================
# 云客API签名 + 调用
# ============================================================

_last_call_time = 0.0

def make_headers():
    ts = str(int(time.time() * 1000))
    sign = hashlib.md5(
        (SIGN_KEY + COMPANY + PARTNER_ID + ts).encode()
    ).hexdigest().upper()
    return {
        "Content-Type": "application/json",
        "partnerId": PARTNER_ID,
        "company": COMPANY,
        "timestamp": ts,
        "sign": sign,
    }

def precise_sleep():
    """精确等待，扣除已消耗时间"""
    global _last_call_time
    if _last_call_time > 0:
        elapsed = time.time() - _last_call_time
        wait = MAX(MIN_INTERVAL - elapsed, 0)
        if wait > 0:
            time.sleep(wait)

def MAX(a, b):
    return a if a > b else b

def call_allrecords(timestamp_ms):
    """
    调用allRecords接口。
    参数 timestamp_ms: 13位毫秒时间戳，API返回该时间点之后1小时内的数据。
    返回 (messages_list, end_timestamp_ms) 或 (None, None) 表示失败。
    """
    global _last_call_time

    for attempt in range(MAX_RETRIES):
        precise_sleep()
        headers = make_headers()
        body = {"timestamp": int(timestamp_ms)}

        try:
            _last_call_time = time.time()
            resp = requests.post(
                f"{API_BASE}/open/wechat/allRecords",
                json=body,
                headers=headers,
                timeout=30,
            )
            data = resp.json()
        except Exception as e:
            log.warning(f"API请求异常: {e}, 重试 {attempt+1}/{MAX_RETRIES}")
            time.sleep(RETRY_SLEEP)
            continue

        if not data.get("success", False):
            msg = data.get("message", "")
            if "频繁" in msg or "请勿" in msg:
                log.warning(f"限流: {msg}, sleep {RETRY_SLEEP}s 后重试")
                time.sleep(RETRY_SLEEP)
                continue
            else:
                log.error(f"API返回失败: {msg}")
                return None, None

        d = data.get("data", {})
        messages = d.get("messages", [])
        end_ts = d.get("end", 0)
        return messages, end_ts

    log.error(f"重试{MAX_RETRIES}次后仍失败，跳过此窗口")
    return None, None

# ============================================================
# 数据转换 + 写入
# ============================================================

def get_sales_wechat_id(msg):
    """从消息中提取销售微信号"""
    return msg.get("wechatId", "")

def build_row(msg):
    """将云客消息转换为chat_messages表行"""
    sales_wxid = get_sales_wechat_id(msg)
    talker = msg.get("talker", "")
    is_mine = msg.get("mine", False)
    room_id = msg.get("roomid") or msg.get("oriTalker") or None
    # msg_type: 统一为数字（API可能返回字符串如"text"/"image"等）
    msg_type_map = {
        'text': 1, 'image': 2, 'voice': 3, 'video': 4,
        'emoticon': 8, 'file': 9, 'link': 10, 'system': 15, 'quote': 21,
    }
    raw_type = msg.get("type", 0)
    if isinstance(raw_type, str):
        msg_type = msg_type_map.get(raw_type.lower(), 0)
    else:
        msg_type = int(raw_type)
    timestamp_ms = msg.get("timestamp", 0)
    msg_svr_id = msg.get("msgSvrId", "")

    if not msg_svr_id:
        return None

    # 判断是否群聊
    is_group = "@chatroom" in str(talker) or (room_id and "@chatroom" in str(room_id))
    if is_group and not room_id:
        room_id = talker

    # sender_type: 双重验证 — mine字段 + wechat_id是否是销售号
    if is_mine or talker in SALES_WECHAT_IDS or talker == sales_wxid:
        sender_type = "sales"
    else:
        sender_type = "customer"

    # wechat_id: 私聊=对方微信ID，群聊=talker(可能是群ID也可能是发言者)
    wechat_id = talker

    # sent_at: 毫秒时间戳转ISO
    if timestamp_ms:
        sent_at = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()
    else:
        sent_at = datetime.now(timezone.utc).isoformat()

    row = {
        "msg_svr_id": str(msg_svr_id),
        "wechat_id": wechat_id,
        "sales_wechat_id": sales_wxid,
        "sender_type": sender_type,
        "content": msg.get("text", ""),
        "msg_type": msg_type,
        "sent_at": sent_at,
        "file_url": msg.get("file") or None,
        "room_id": room_id,
    }
    return row

def batch_upsert(rows):
    """批量upsert到chat_messages，返回成功写入数

    语音消息(msg_type=3)特殊处理：不覆盖已有的content字段，
    因为transcribe_voice.py可能已经写入了转写结果。
    """
    if not rows:
        return 0

    sb = get_sb()
    written = 0

    # 分离语音消息和非语音消息
    voice_rows = [r for r in rows if r.get("msg_type") == 3]
    other_rows = [r for r in rows if r.get("msg_type") != 3]

    # 非语音消息：正常upsert
    for i in range(0, len(other_rows), BATCH_SIZE):
        batch = other_rows[i:i + BATCH_SIZE]
        try:
            sb.table("chat_messages").upsert(
                batch, on_conflict="msg_svr_id"
            ).execute()
            written += len(batch)
        except Exception as e:
            err_msg = str(e)
            if "duplicate" in err_msg.lower() or "conflict" in err_msg.lower() or "dedup" in err_msg.lower():
                for row in batch:
                    try:
                        sb.table("chat_messages").upsert(
                            row, on_conflict="msg_svr_id"
                        ).execute()
                        written += 1
                    except Exception:
                        pass
            else:
                log.error(f"写入失败: {err_msg}")

    # 语音消息：去掉content字段再upsert，避免覆盖转写结果
    for i in range(0, len(voice_rows), BATCH_SIZE):
        batch = []
        for row in voice_rows[i:i + BATCH_SIZE]:
            safe_row = {k: v for k, v in row.items() if k != "content"}
            batch.append(safe_row)
        try:
            sb.table("chat_messages").upsert(
                batch, on_conflict="msg_svr_id"
            ).execute()
            written += len(batch)
        except Exception as e:
            err_msg = str(e)
            if "duplicate" in err_msg.lower() or "conflict" in err_msg.lower() or "dedup" in err_msg.lower():
                for row in batch:
                    try:
                        sb.table("chat_messages").upsert(
                            row, on_conflict="msg_svr_id"
                        ).execute()
                        written += 1
                    except Exception:
                        pass
            else:
                log.error(f"语音写入失败: {err_msg}")

    return written

# ============================================================
# 状态文件管理
# ============================================================

def read_cursor(filepath):
    """读取游标文件，返回毫秒时间戳，不存在返回None"""
    try:
        with open(filepath, "r") as f:
            val = f.read().strip()
            return int(val)
    except (FileNotFoundError, ValueError):
        return None

def write_cursor(filepath, ts_ms):
    """写入游标文件"""
    with open(filepath, "w") as f:
        f.write(str(int(ts_ms)))

# ============================================================
# 增量模式（cron每小时跑）
# ============================================================

def run_incremental():
    """
    增量拉取：从上次游标开始，拉到当前时间-30分钟。
    如果没有游标，从2小时前开始。
    """
    now_ms = int(time.time() * 1000)
    lag_ms = LAG_MINUTES * 60 * 1000
    end_boundary = now_ms - lag_ms

    cursor = read_cursor(CURSOR_FILE)
    if cursor is None:
        # 首次运行，从2小时前开始
        cursor = now_ms - 2 * 3600 * 1000
        log.info("无游标，从2小时前开始")

    log.info(f"增量拉取: {ts_to_str(cursor)} → {ts_to_str(end_boundary)}")

    total_fetched = 0
    total_written = 0
    current_ts = cursor

    while current_ts < end_boundary:
        messages, end_ts = call_allrecords(current_ts)

        if messages is None:
            # API失败，推进1小时避免死循环
            current_ts += 3600 * 1000
            continue

        if messages:
            rows = [r for r in (build_row(m) for m in messages) if r]
            written = batch_upsert(rows)
            total_fetched += len(messages)
            total_written += written
            log.info(f"  {ts_to_str(current_ts)}: {len(messages)}条, 写入{written}")

        # 推进1小时
        current_ts += 3600 * 1000

        # 保存游标
        write_cursor(CURSOR_FILE, current_ts)

    log.info(f"增量完成: 拉取{total_fetched}, 写入{total_written}")

# ============================================================
# 回补模式（一次性全量扫描）
# ============================================================

def run_backfill(start_date_str=None, resume=False):
    """
    回补模式：从指定日期扫描到当前时间-30分钟。
    支持指数跳跃加速空窗口扫描。
    """
    now_ms = int(time.time() * 1000)
    lag_ms = LAG_MINUTES * 60 * 1000
    end_boundary = now_ms - lag_ms

    # 确定起始时间
    if resume:
        cursor = read_cursor(BACKFILL_FILE)
        if cursor:
            current_ts = cursor
            log.info(f"从断点续传: {ts_to_str(current_ts)}")
        else:
            log.error("无断点文件，请指定 --start")
            sys.exit(1)
    elif start_date_str:
        dt = datetime.strptime(start_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        current_ts = int(dt.timestamp() * 1000)
        log.info(f"回补起始: {start_date_str}")
    else:
        log.error("请指定 --start YYYY-MM-DD 或 --resume")
        sys.exit(1)

    total_hours = (end_boundary - current_ts) // (3600 * 1000)
    log.info(f"需扫描约 {total_hours} 小时窗口")

    total_fetched = 0
    total_written = 0
    empty_streak = 0
    skip_idx = 0  # 当前跳跃步长索引
    rounds = 0

    while current_ts < end_boundary:
        rounds += 1
        messages, end_ts = call_allrecords(current_ts)

        if messages is None:
            # API失败，推进1小时
            current_ts += 3600 * 1000
            write_cursor(BACKFILL_FILE, current_ts)
            continue

        if messages:
            rows = [r for r in (build_row(m) for m in messages) if r]
            written = batch_upsert(rows)
            total_fetched += len(messages)
            total_written += written

            # 命中数据，重置跳跃
            if empty_streak > 0:
                log.info(f"  跳过{empty_streak}个空窗口后命中数据")
            empty_streak = 0
            skip_idx = 0

            progress = (current_ts - (end_boundary - total_hours * 3600 * 1000)) / (total_hours * 3600 * 1000) * 100
            log.info(
                f"  轮{rounds} [{progress:.1f}%] {ts_to_str(current_ts)}: "
                f"{len(messages)}条, 写入{written} | 累计: 拉{total_fetched}, 写{total_written}"
            )

            # 推进1小时
            current_ts += 3600 * 1000
        else:
            # 空窗口，指数跳跃
            empty_streak += 1
            step_hours = SKIP_STEPS[min(skip_idx, len(SKIP_STEPS) - 1)]
            current_ts += step_hours * 3600 * 1000

            # 升级跳跃步长
            if empty_streak % 3 == 0 and skip_idx < len(SKIP_STEPS) - 1:
                skip_idx += 1

            # 每100个空窗口报告一次
            if empty_streak % 100 == 0:
                progress = min(99.9, (current_ts - (end_boundary - total_hours * 3600 * 1000)) / max(1, total_hours * 3600 * 1000) * 100)
                log.info(
                    f"  轮{rounds} [{progress:.1f}%] 连续{empty_streak}个空窗口, "
                    f"当前步长{step_hours}h | 累计: 拉{total_fetched}, 写{total_written}"
                )

        # 保存断点
        write_cursor(BACKFILL_FILE, current_ts)

    log.info(f"回补完成: 共{rounds}轮, 拉取{total_fetched}, 写入{total_written}")

# ============================================================
# 工具函数
# ============================================================

def ts_to_str(ts_ms):
    """毫秒时间戳转可读字符串"""
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")

# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="云客聊天记录拉取 v2")
    parser.add_argument("--backfill", action="store_true", help="回补模式（全量扫描）")
    parser.add_argument("--start", type=str, help="回补起始日期 YYYY-MM-DD")
    parser.add_argument("--resume", action="store_true", help="从断点续传")
    args = parser.parse_args()

    log.info("=" * 50)
    if args.backfill:
        log.info("yunke_pull_chat_v2.py 回补模式启动")
        run_backfill(start_date_str=args.start, resume=args.resume)
    else:
        log.info("yunke_pull_chat_v2.py 增量模式启动")
        run_incremental()
    log.info("=" * 50)

if __name__ == "__main__":
    main()
