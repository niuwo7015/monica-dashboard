#!/usr/bin/env python3
"""
云客聊天记录历史回补脚本
- allRecords：固定1小时窗口逐段扫描私聊消息（带分页），不依赖API end跳转
- records：逐群拉取群聊消息，按3天窗口分段
- 批量upsert（50条/批），动态休眠
- 从2025年9月1日开始，拉取到当前时间
"""

import os
import sys
import time
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone

import requests
from supabase import create_client

# ============ 配置 ============
COMPANY = os.getenv('YUNKE_COMPANY', '5fri8k')
PARTNER_ID = os.getenv('YUNKE_PARTNER_ID', 'pDB33ABE148934DD081FD7D4C80654195')
SIGN_KEY = os.getenv('YUNKE_SIGN_KEY', 'F446226EBF084CF6AAC00E')
API_BASE = os.getenv('YUNKE_API_BASE', 'https://phone.yunkecn.com')
SUPABASE_URL = os.getenv('SUPABASE_URL', 'https://dieeejjzbhkpgxdhwlxf.supabase.co')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')

# 回补起始时间：2025年9月1日
BACKFILL_START = datetime(2025, 9, 1)

if not SUPABASE_KEY:
    print("ERROR: SUPABASE_SERVICE_ROLE_KEY 环境变量未设置")
    sys.exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ============ 日志 ============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ============ 销售微信号映射 (复用pull_chat逻辑) ============
SALES_WECHAT_MAP = {
    'wxid_am3kdib9tt3722': {'name': '可欣(乐乐)', 'email': 'kexin@test.com'},
    'wxid_p03xoj66oss112': {'name': '小杰(jay)', 'email': 'xiaojie@test.com'},
    'wxid_cbk7hkyyp11t12': {'name': '霄剑(Chen)', 'email': 'xiaojian@test.com'},
    'wxid_aufah51bw9ok22': {'name': 'Fiona', 'email': None},
    'wxid_idjldooyihpj22': {'name': '晴天喵', 'email': None},
    'wxid_rxc39paqvic522': {'name': 'Joy', 'email': None},
}

_sales_id_cache = {}


def get_sales_id(wechat_id):
    """通过销售微信号获取sales_id"""
    info = SALES_WECHAT_MAP.get(wechat_id)
    if not info or not info['email']:
        return None
    email = info['email']
    if email in _sales_id_cache:
        return _sales_id_cache[email]
    try:
        result = supabase.table('users').select('id').eq('email', email).execute()
        if result.data:
            _sales_id_cache[email] = result.data[0]['id']
            return _sales_id_cache[email]
    except Exception as e:
        logger.warning(f"查询sales_id失败 email={email}: {e}")
    return None


def get_customer_id(wechat_id, sales_wechat_id):
    """通过微信号查contacts表获取customer_id"""
    try:
        result = supabase.table('contacts').select('customer_id').eq(
            'wechat_id', wechat_id
        ).eq('sales_wechat_id', sales_wechat_id).execute()
        if result.data and result.data[0].get('customer_id'):
            return result.data[0]['customer_id']
    except Exception as e:
        pass  # 静默处理，回补时contacts表可能还没数据
    return None


def make_sign(timestamp_ms):
    """生成云客API签名"""
    raw = f"{SIGN_KEY}{COMPANY}{PARTNER_ID}{timestamp_ms}"
    return hashlib.md5(raw.encode()).hexdigest().upper()


def pull_one_batch(create_timestamp):
    """拉取一批聊天记录（1小时数据）"""
    timestamp_ms = str(int(time.time() * 1000))
    sign = make_sign(timestamp_ms)

    headers = {
        'partnerId': PARTNER_ID,
        'company': COMPANY,
        'timestamp': timestamp_ms,
        'sign': sign,
        'Content-Type': 'application/json'
    }

    body = {
        'timestamp': timestamp_ms,
        'createTimestamp': int(create_timestamp)
    }

    url = f"{API_BASE}/open/wechat/allRecords"

    for retry in range(3):
        try:
            resp = requests.post(url, json=body, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            # API may return {code: 0/200, data: ...} or {success: true, data: ...}
            is_success = data.get('code') in (0, 200) or data.get('success') is True
            if not is_success:
                logger.warning(f"API返回错误: {data}")
                if retry < 2:
                    time.sleep(10)
                    continue
                return None

            return data.get('data', {})
        except Exception as e:
            logger.error(f"API请求失败 (retry {retry+1}/3): {e}")
            if retry < 2:
                time.sleep(10)
    return None


def timestamp_ms_to_iso(ts_ms):
    """毫秒时间戳转ISO格式(UTC)"""
    if not ts_ms:
        return None
    try:
        ts_sec = int(ts_ms) / 1000
        return datetime.fromtimestamp(ts_sec, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')
    except (ValueError, TypeError, OSError):
        return None


def build_row_from_record(record):
    """将API记录转换为数据库行"""
    msg_svr_id = record.get('msgSvrId')
    if not msg_svr_id:
        return None

    is_mine = record.get('mine', False)
    sender_type = 'sales' if is_mine else 'customer'
    wechat_id_field = record.get('wechatId', '')
    talker = record.get('talker', '')

    sales_id = get_sales_id(wechat_id_field)
    sales_wechat_id = wechat_id_field if wechat_id_field in SALES_WECHAT_MAP else None

    customer_id = None
    if talker and sales_wechat_id:
        customer_id = get_customer_id(talker, sales_wechat_id)

    row = {
        'msg_svr_id': str(msg_svr_id),
        'wechat_id': talker,
        'sender_type': sender_type,
        'content': record.get('text', ''),
        'msg_type': str(record.get('type', '')),
        'sent_at': timestamp_ms_to_iso(record.get('timestamp')),
        'file_url': record.get('file', ''),
        'room_id': record.get('roomid', ''),
    }

    if sales_id:
        row['sales_id'] = sales_id
    if customer_id:
        row['customer_id'] = customer_id

    for k, v in row.items():
        if v == '':
            row[k] = None

    return row


def batch_upsert(rows, batch_size=50):
    """批量upsert到chat_messages，失败时回退逐条写入"""
    if not rows:
        return 0, 0

    inserted = 0
    skipped = 0

    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        try:
            supabase.table('chat_messages').upsert(
                batch,
                on_conflict='msg_svr_id'
            ).execute()
            inserted += len(batch)
        except Exception as e:
            logger.warning(f"批量写入失败({len(batch)}条): {e}，回退逐条写入")
            for row in batch:
                try:
                    supabase.table('chat_messages').upsert(
                        row,
                        on_conflict='msg_svr_id'
                    ).execute()
                    inserted += 1
                except Exception as e2:
                    logger.warning(f"写入失败 msg_svr_id={row.get('msg_svr_id')}: {e2}")
                    skipped += 1

    return inserted, skipped


def process_records(records):
    """处理并批量写入allRecords聊天记录"""
    if not records:
        return 0, 0

    rows = []
    skipped = 0

    for record in records:
        row = build_row_from_record(record)
        if row:
            rows.append(row)
        else:
            skipped += 1

    inserted, write_skipped = batch_upsert(rows)
    return inserted, skipped + write_skipped


def get_latest_sent_at():
    """获取chat_messages中最新的sent_at"""
    try:
        result = supabase.table('chat_messages').select('sent_at').order(
            'sent_at', desc=True
        ).limit(1).execute()
        if result.data and result.data[0].get('sent_at'):
            return result.data[0]['sent_at']
    except Exception as e:
        logger.warning(f"查询最新sent_at失败: {e}")
    return None


def iso_to_timestamp_ms(iso_str):
    """ISO时间转毫秒时间戳"""
    try:
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        return int(dt.timestamp() * 1000)
    except (ValueError, TypeError):
        return None


def yunke_api_call(path, body):
    """通用云客API调用（带签名和重试）"""
    timestamp_ms = str(int(time.time() * 1000))
    sign = make_sign(timestamp_ms)
    headers = {
        'partnerId': PARTNER_ID,
        'company': COMPANY,
        'timestamp': timestamp_ms,
        'sign': sign,
        'Content-Type': 'application/json'
    }
    for retry in range(3):
        try:
            resp = requests.post(f"{API_BASE}{path}", json=body, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            is_success = data.get('code') in (0, 200) or data.get('success') is True
            if not is_success:
                logger.warning(f"API返回错误 {path}: {data.get('message', data)}")
                if retry < 2:
                    time.sleep(10)
                    continue
                return None
            return data.get('data', {})
        except Exception as e:
            logger.error(f"API请求失败 {path} (retry {retry+1}/3): {e}")
            if retry < 2:
                time.sleep(10)
    return None


# ============ 群聊回补（records接口） ============

def pull_group_list():
    """通过friends接口获取所有群ID，返回 [(group_id, sales_wechat_id), ...]"""
    groups = []
    seen = set()

    for wechat_id in SALES_WECHAT_MAP:
        page = 1
        while True:
            data = yunke_api_call('/open/wechat/friends', {
                'wechatId': wechat_id,
                'pageIndex': page,
                'pageSize': 100,
                'type': 2,
            })
            time.sleep(8)

            if not data:
                break

            items = data.get('page', [])
            for item in items:
                gid = item.get('id', '')
                if '@chatroom' in gid and gid not in seen:
                    seen.add(gid)
                    groups.append((gid, wechat_id))

            if len(items) < 100:
                break
            page += 1

        logger.info(f"  {wechat_id}: 累计发现 {len(seen)} 个群")

    return groups


def pull_group_records(group_id, wechat_id, start_date=None, end_date=None):
    """用records接口拉取一个群的聊天记录，返回消息列表"""
    all_msgs = []
    body = {
        'friendWechatId': group_id,
        'wechatId': wechat_id,
        'userId': PARTNER_ID,
    }
    if start_date:
        body['startDate'] = start_date
    if end_date:
        body['endDate'] = end_date

    rounds = 0
    while rounds < 50:
        rounds += 1
        data = yunke_api_call('/open/wechat/records', body)
        time.sleep(8)

        if not data:
            break

        msgs = data.get('messages', [])
        all_msgs.extend(msgs)

        if not data.get('hasNext') or not msgs:
            break

        body['start'] = data.get('end')

    return all_msgs


def process_group_records(records, group_id, sales_wechat_id):
    """处理records接口返回的群聊消息并批量写入（talker=发言者wxid）"""
    if not records:
        return 0, 0

    rows = []
    skipped = 0
    sales_id = get_sales_id(sales_wechat_id)

    for record in records:
        msg_svr_id = record.get('msgSvrId')
        if not msg_svr_id:
            skipped += 1
            continue

        is_mine = record.get('mine', False)
        sender_type = 'sales' if is_mine else 'customer'

        # records接口: talker=发言者wxid, oriTalker/roomid=群ID
        sender_wxid = record.get('talker', '')
        room_id = record.get('oriTalker') or record.get('roomid') or group_id

        customer_id = None
        if not is_mine and sender_wxid and sales_wechat_id:
            customer_id = get_customer_id(sender_wxid, sales_wechat_id)

        row = {
            'msg_svr_id': str(msg_svr_id),
            'wechat_id': sender_wxid,
            'sender_type': sender_type,
            'content': record.get('text', ''),
            'msg_type': str(record.get('type', '')),
            'sent_at': timestamp_ms_to_iso(record.get('timestamp')),
            'file_url': record.get('file', ''),
            'room_id': room_id,
        }

        if sales_id:
            row['sales_id'] = sales_id
        if customer_id:
            row['customer_id'] = customer_id

        for k, v in row.items():
            if v == '':
                row[k] = None

        rows.append(row)

    inserted, write_skipped = batch_upsert(rows)
    return inserted, skipped + write_skipped


def get_group_latest_sent_at(group_id):
    """查询某个群在chat_messages中最新的sent_at"""
    try:
        result = supabase.table('chat_messages').select('sent_at').eq(
            'room_id', group_id
        ).order('sent_at', desc=True).limit(1).execute()
        if result.data and result.data[0].get('sent_at'):
            return result.data[0]['sent_at']
    except Exception:
        pass
    return None


def backfill_group_chats():
    """回补所有群聊记录：逐群拉取，按3天窗口分段（优化版）"""
    logger.info("=" * 60)
    logger.info("开始群聊历史回补（records接口，优化版）")

    groups = pull_group_list()
    logger.info(f"共发现 {len(groups)} 个群")

    now = datetime.now()
    total_pulled = 0
    total_inserted = 0
    total_skipped = 0
    skipped_groups = 0

    for i, (group_id, wechat_id) in enumerate(groups):
        group_pulled = 0
        group_inserted = 0

        # 查询该群已有数据的最新时间，从那之后开始回补
        existing_latest = get_group_latest_sent_at(group_id)
        if existing_latest:
            try:
                window_start = datetime.fromisoformat(existing_latest.replace('Z', '+00:00')).replace(tzinfo=None)
                logger.info(f"  群[{i+1}/{len(groups)}] {group_id}: 已有数据到 {existing_latest}，增量回补")
            except (ValueError, TypeError):
                window_start = BACKFILL_START
        else:
            window_start = BACKFILL_START

        empty_streak = 0  # 连续空窗口计数

        while window_start < now:
            # 连续3个空窗口后跳到更大步长（7天）
            if empty_streak >= 3:
                window_end = min(window_start + timedelta(days=7), now)
            else:
                window_end = min(window_start + timedelta(days=3), now)

            start_str = window_start.strftime('%Y-%m-%d %H:%M:%S')
            end_str = window_end.strftime('%Y-%m-%d %H:%M:%S')

            msgs = pull_group_records(group_id, wechat_id, start_str, end_str)
            if msgs:
                inserted, skipped = process_group_records(msgs, group_id, wechat_id)
                group_pulled += len(msgs)
                group_inserted += inserted
                total_skipped += skipped
                empty_streak = 0
            else:
                empty_streak += 1

            window_start = window_end

        total_pulled += group_pulled
        total_inserted += group_inserted

        if group_pulled > 0:
            logger.info(
                f"  群[{i+1}/{len(groups)}] {group_id}: "
                f"拉取{group_pulled}条, 写入{group_inserted}条"
            )
        else:
            skipped_groups += 1
            if (i + 1) % 20 == 0:
                logger.info(f"  进度: {i+1}/{len(groups)} 个群已处理")

    logger.info("=" * 60)
    logger.info(
        f"群聊回补完成: 共{len(groups)}个群({skipped_groups}个无数据), "
        f"总拉取{total_pulled}条, 总写入{total_inserted}条, 总跳过{total_skipped}条"
    )
    logger.info("=" * 60)
    return total_pulled, total_inserted, total_skipped


def backfill_all_records():
    """
    allRecords回补：固定1小时窗口逐段扫描，带内层分页。
    关键修复：不依赖API返回的end来推进时间，固定每次前进1小时，
    确保每个小时都被查询到。
    """
    logger.info("=" * 60)
    logger.info(f"开始allRecords私聊历史回补（从 {BACKFILL_START} 起）")

    start_ts = int(BACKFILL_START.timestamp() * 1000)
    now_ts = int(time.time() * 1000)
    current_ts = start_ts

    total_pulled = 0
    total_inserted = 0
    total_skipped = 0
    round_num = 0
    empty_rounds = 0

    estimated_hours = (now_ts - current_ts) / (3600 * 1000)
    logger.info(f"需要扫描 {estimated_hours:.0f} 个小时窗口")

    while current_ts < now_ts:
        round_num += 1
        round_records = []

        # ---- 内层分页循环：对当前createTimestamp做分页 ----
        fetch_ts = current_ts
        page = 0

        while True:
            page += 1
            data = pull_one_batch(fetch_ts)

            if data is None:
                break

            records = data.get('messages', data.get('list', []))
            round_records.extend(records)

            end_ts = data.get('end', 0)
            has_next = data.get('hasNext', False)

            # 继续分页条件：有hasNext + end前进了 + 本批有数据
            if has_next and end_ts and int(end_ts) > fetch_ts and records:
                fetch_ts = int(end_ts)
                time.sleep(3)
            else:
                break

        # ---- 批量写入 ----
        if round_records:
            inserted, skipped = process_records(round_records)
            total_pulled += len(round_records)
            total_inserted += inserted
            total_skipped += skipped
            empty_rounds = 0
        else:
            empty_rounds += 1

        # ---- 进度日志 ----
        progress = (current_ts - start_ts) / max(now_ts - start_ts, 1) * 100
        time_str = datetime.fromtimestamp(current_ts / 1000).strftime('%Y-%m-%d %H:%M')

        if round_records:
            logger.info(
                f"第{round_num}轮 [{progress:.1f}%] {time_str}: "
                f"本轮{len(round_records)}条({page}页) "
                f"| 累计: 拉取{total_pulled}, 写入{total_inserted}"
            )
        elif round_num % 100 == 0:
            logger.info(
                f"第{round_num}轮 [{progress:.1f}%] {time_str}: "
                f"空窗口(连续{empty_rounds}个) | 累计: 拉取{total_pulled}"
            )

        # ★ 关键修复：固定前进1小时，绝不依赖API的end跳转 ★
        current_ts += 3600 * 1000

        # 动态休眠：连续空窗口时缩短等待
        if empty_rounds > 20:
            time.sleep(2)
        elif empty_rounds > 5:
            time.sleep(3)
        else:
            time.sleep(5)

    logger.info(
        f"allRecords回补完成: 拉取{total_pulled}条, 写入{total_inserted}条, "
        f"跳过{total_skipped}条, 共{round_num}个小时窗口"
    )
    logger.info("=" * 60)
    return total_pulled, total_inserted, total_skipped


def main():
    logger.info("=" * 60)
    logger.info("开始历史回补（全量）")
    logger.info("=" * 60)

    # 第一步：allRecords回补私聊消息
    backfill_all_records()

    # 第二步：records接口回补群聊消息
    backfill_group_chats()

    logger.info("=" * 60)
    logger.info("全部回补完成!")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
