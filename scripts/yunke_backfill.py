#!/usr/bin/env python3
"""
云客聊天记录历史回补脚本
- 从2025年8月1日开始，拉取到当前时间
- 支持中断续跑：从Supabase查最新记录时间继续
- 每次1小时数据，5秒间隔
"""

import os
import sys
import time
import hashlib
import json
import logging
from datetime import datetime, timedelta

import requests
from supabase import create_client

# ============ 配置 ============
COMPANY = os.getenv('YUNKE_COMPANY', '5fri8k')
PARTNER_ID = os.getenv('YUNKE_PARTNER_ID', 'pDB33ABE148934DD081FD7D4C80654195')
SIGN_KEY = os.getenv('YUNKE_SIGN_KEY', 'F446226EBF084CF6AAC00E')
API_BASE = os.getenv('YUNKE_API_BASE', 'https://phone.yunkecn.com')
SUPABASE_URL = os.getenv('SUPABASE_URL', 'https://dieeejjzbhkpgxdhwlxf.supabase.co')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')

# 回补起始时间：2025年8月1日
BACKFILL_START = datetime(2025, 8, 1)

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
    """毫秒时间戳转ISO格式"""
    if not ts_ms:
        return None
    try:
        ts_sec = int(ts_ms) / 1000
        return datetime.fromtimestamp(ts_sec).isoformat()
    except (ValueError, TypeError, OSError):
        return None


def process_records(records):
    """处理并写入聊天记录"""
    if not records:
        return 0, 0

    inserted = 0
    skipped = 0

    for record in records:
        msg_svr_id = record.get('msgSvrId')
        if not msg_svr_id:
            skipped += 1
            continue

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

        try:
            supabase.table('chat_messages').upsert(
                row,
                on_conflict='msg_svr_id'
            ).execute()
            inserted += 1
        except Exception as e:
            logger.warning(f"写入失败 msg_svr_id={msg_svr_id}: {e}")
            skipped += 1

    return inserted, skipped


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


def main():
    logger.info("=" * 60)
    logger.info("开始历史回补（从2025年8月1日起）")

    # 中断续跑：查最新记录
    latest = get_latest_sent_at()
    if latest:
        resume_ts = iso_to_timestamp_ms(latest)
        backfill_start_ts = int(BACKFILL_START.timestamp() * 1000)
        if resume_ts and resume_ts > backfill_start_ts:
            start_ts = resume_ts
            logger.info(f"续跑模式: 从 {latest} 继续")
        else:
            start_ts = backfill_start_ts
            logger.info(f"从头开始: {BACKFILL_START}")
    else:
        start_ts = int(BACKFILL_START.timestamp() * 1000)
        logger.info(f"表为空，从 {BACKFILL_START} 开始回补")

    current_ts = start_ts
    now_ts = int(time.time() * 1000)
    total_pulled = 0
    total_inserted = 0
    total_skipped = 0
    round_num = 0

    estimated_hours = (now_ts - current_ts) / (3600 * 1000)
    logger.info(f"预计需要处理 {estimated_hours:.0f} 小时的数据")

    while current_ts < now_ts:
        round_num += 1
        data = pull_one_batch(current_ts)

        if data is None:
            logger.error(f"第{round_num}轮拉取失败，跳过1小时继续")
            current_ts += 3600 * 1000
            time.sleep(5)
            continue

        records = data.get('messages', data.get('list', []))
        end_ts = data.get('end', 0)

        pulled = len(records)
        inserted, skipped = process_records(records)

        total_pulled += pulled
        total_inserted += inserted
        total_skipped += skipped

        # 计算进度
        progress = (current_ts - start_ts) / max(now_ts - start_ts, 1) * 100
        current_time_str = datetime.fromtimestamp(current_ts / 1000).strftime('%Y-%m-%d %H:%M')

        if round_num % 10 == 0 or pulled > 0:
            logger.info(
                f"第{round_num}轮 [{progress:.1f}%] {current_time_str}: "
                f"拉取{pulled}条, 写入{inserted}条, 跳过{skipped}条 "
                f"| 累计: 拉取{total_pulled}, 写入{total_inserted}"
            )

        if end_ts and int(end_ts) > current_ts:
            current_ts = int(end_ts)
        else:
            # 没有返回end，手动往前推1小时
            current_ts += 3600 * 1000

        time.sleep(5)

    logger.info("=" * 60)
    logger.info(
        f"回补完成! 总计: 拉取{total_pulled}条, 写入{total_inserted}条, "
        f"跳过{total_skipped}条, 共{round_num}轮"
    )
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
