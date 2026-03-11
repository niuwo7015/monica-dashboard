#!/usr/bin/env python3
"""
T-021: 报价标记 — 扫描chat_messages识别销售报价，标记contacts.has_quote
- 只看销售发出的纯文本私聊消息
- 关键词/正则匹配报价行为
- 排除手机号、含"电话/微信号/手机"的消息
- 按wechat_id聚合，取最早报价时间写入contacts
- 支持 --dry-run 模式
"""

import os
import re
import sys
import argparse
import logging
from datetime import datetime
from collections import defaultdict

from supabase import create_client

# ============ 配置 ============
SUPABASE_URL = os.getenv('SUPABASE_URL', 'https://dieeejjzbhkpgxdhwlxf.supabase.co')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')

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

# ============ 报价匹配规则 ============

# 排除规则：含这些关键词的消息不算报价
EXCLUDE_KEYWORDS = ['电话', '微信号', '手机']

# 排除：11位连续数字（手机号）
RE_PHONE = re.compile(r'\d{11}')

# 匹配规则（任一命中即算报价）
# 1. 含 ¥ + 数字
RE_YEN_PRICE = re.compile(r'¥\s*\d+')
# 2. 含 报价/优惠价/折后/特价/活动价
QUOTE_KEYWORDS = ['报价', '优惠价', '折后', '特价', '活动价']
# 3. 含 数字+元
RE_YUAN = re.compile(r'\d+元')
# 4. 含 数字+万
RE_WAN = re.compile(r'\d+万')
# 5. 含4-6位连续数字 且 同时含产品关键词
RE_PRICE_DIGITS = re.compile(r'\d{4,6}')
PRODUCT_KEYWORDS = ['价', '沙发', '茶几', '床', '柜']


def is_quote_message(content):
    """判断消息内容是否为报价消息"""
    if not content:
        return False

    # 排除：含排除关键词
    for kw in EXCLUDE_KEYWORDS:
        if kw in content:
            return False

    # 排除：含11位连续数字（手机号）
    if RE_PHONE.search(content):
        return False

    # 规则1: ¥ + 数字
    if RE_YEN_PRICE.search(content):
        return True

    # 规则2: 报价关键词
    for kw in QUOTE_KEYWORDS:
        if kw in content:
            return True

    # 规则3: 数字+元
    if RE_YUAN.search(content):
        return True

    # 规则4: 数字+万
    if RE_WAN.search(content):
        return True

    # 规则5: 4-6位数字 + 产品关键词共现
    if RE_PRICE_DIGITS.search(content):
        for kw in PRODUCT_KEYWORDS:
            if kw in content:
                return True

    return False


def fetch_sales_text_messages():
    """
    分页拉取所有符合条件的销售纯文本私聊消息。
    条件：sender_type=sales, is_system_msg=false, msg_type=1, 非群聊
    返回消息列表 [{wechat_id, sales_wechat_id, content, sent_at}, ...]
    """
    all_messages = []
    page_size = 1000
    offset = 0

    while True:
        result = supabase.table('chat_messages').select(
            'wechat_id, sales_wechat_id, content, sent_at, room_id'
        ).eq(
            'sender_type', 'sales'
        ).eq(
            'is_system_msg', False
        ).eq(
            'msg_type', 1
        ).order(
            'sent_at', desc=False
        ).range(offset, offset + page_size - 1).execute()

        if not result.data:
            break

        for msg in result.data:
            # 跳过群聊消息（room_id含@chatroom）
            room_id = msg.get('room_id') or ''
            if '@chatroom' in room_id:
                continue
            all_messages.append(msg)

        if len(result.data) < page_size:
            break
        offset += page_size

    return all_messages


def scan_quotes(messages):
    """
    扫描消息列表，返回报价统计。
    返回:
        quote_contacts: {(wechat_id, sales_wechat_id): earliest_sent_at}
        hit_count: 命中报价的消息总数
        samples: 抽样命中消息（最多10条）
    """
    # {(wechat_id, sales_wechat_id): earliest_sent_at}
    quote_contacts = {}
    hit_count = 0
    samples = []

    for msg in messages:
        content = msg.get('content') or ''
        if not is_quote_message(content):
            continue

        hit_count += 1
        wechat_id = msg.get('wechat_id')
        sales_wechat_id = msg.get('sales_wechat_id')
        sent_at = msg.get('sent_at')

        if not wechat_id or not sales_wechat_id:
            continue

        key = (wechat_id, sales_wechat_id)
        # 取最早的报价时间（消息已按sent_at asc排序）
        if key not in quote_contacts:
            quote_contacts[key] = sent_at

        # 抽样前10条
        if len(samples) < 10:
            samples.append({
                'wechat_id': wechat_id,
                'sales_wechat_id': sales_wechat_id,
                'sent_at': sent_at,
                'content': content[:100],  # 截断避免过长
            })

    return quote_contacts, hit_count, samples


def update_contacts(quote_contacts, dry_run=False):
    """批量更新contacts表的has_quote和first_quote_at"""
    if not quote_contacts:
        logger.info("无需更新：没有匹配到报价客户")
        return 0

    if dry_run:
        logger.info(f"DRY-RUN: 将标记 {len(quote_contacts)} 个客户 has_quote=true")
        return len(quote_contacts)

    updated = 0
    batch_size = 50
    items = list(quote_contacts.items())

    for i in range(0, len(items), batch_size):
        batch = items[i:i + batch_size]
        for (wechat_id, sales_wechat_id), first_quote_at in batch:
            try:
                supabase.table('contacts').update({
                    'has_quote': True,
                    'first_quote_at': first_quote_at,
                }).eq(
                    'wechat_id', wechat_id
                ).eq(
                    'sales_wechat_id', sales_wechat_id
                ).execute()
                updated += 1
            except Exception as e:
                logger.warning(f"更新失败 wechat_id={wechat_id}: {e}")

    return updated


def main():
    parser = argparse.ArgumentParser(description='T-021 报价标记 — 扫描聊天记录标记报价客户')
    parser.add_argument('--dry-run', action='store_true', help='只输出不写库')
    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info(f"T-021 报价标记 {'(DRY-RUN)' if args.dry_run else ''}")
    logger.info("=" * 50)

    # 1. 拉取销售纯文本私聊消息
    logger.info("正在拉取销售纯文本私聊消息...")
    messages = fetch_sales_text_messages()
    logger.info(f"拉取到 {len(messages)} 条销售私聊文本消息")

    # 2. 扫描报价
    logger.info("正在扫描报价关键词...")
    quote_contacts, hit_count, samples = scan_quotes(messages)

    # 3. 输出统计
    logger.info("=" * 50)
    logger.info(f"扫描结果:")
    logger.info(f"  总扫描销售消息数: {len(messages)}")
    logger.info(f"  命中报价的消息数: {hit_count}")
    logger.info(f"  涉及客户数(has_quote): {len(quote_contacts)}")

    # 抽样展示
    if samples:
        logger.info("=" * 50)
        logger.info("抽样命中消息（前10条）:")
        for i, s in enumerate(samples):
            logger.info(
                f"  [{i+1}] wechat_id={s['wechat_id']} | "
                f"sales={s['sales_wechat_id']} | "
                f"time={s['sent_at']} | "
                f"content: {s['content']}"
            )

    # 4. 写入contacts
    logger.info("=" * 50)
    updated = update_contacts(quote_contacts, dry_run=args.dry_run)

    if args.dry_run:
        logger.info(f"DRY-RUN完成 — 将标记 {updated} 个客户")
    else:
        logger.info(f"写入完成: {updated} 个客户已标记 has_quote=true")

    logger.info("=" * 50)
    logger.info("T-021 完成")


if __name__ == '__main__':
    main()
