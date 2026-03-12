#!/usr/bin/env python3
"""
T-021: 补齐 orders 表 deal_cycle_days

逻辑：
1. 先重跑 yunke_pull_friends 同步 contacts.add_time（从云客API拉最新）
2. 查 orders 表 deal_cycle_days IS NULL 且有 wechat_id 的记录
3. 用 wechat_id 反查 contacts 表拿 add_time
4. deal_cycle_days = order_date - add_time（天数）
5. 更新 orders 表

用法：
  python3 backfill_deal_cycle.py              # 先同步好友再补
  python3 backfill_deal_cycle.py --skip-sync  # 跳过好友同步，直接补
  python3 backfill_deal_cycle.py --dry-run    # 只看不写
"""

import os
import sys
import logging
import argparse
from datetime import datetime

from supabase import create_client

# ============ 配置 ============
SUPABASE_URL = os.getenv('SUPABASE_URL', 'https://dieeejjzbhkpgxdhwlxf.supabase.co')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')

if not SUPABASE_KEY:
    print("ERROR: SUPABASE_SERVICE_ROLE_KEY 环境变量未设置")
    sys.exit(1)

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def sync_friends():
    """调用 yunke_pull_friends 同步 contacts.add_time"""
    logger.info("=" * 50)
    logger.info("Step 1: 重跑 yunke_pull_friends 同步 add_time")
    logger.info("=" * 50)
    # 直接import并调用
    import yunke_pull_friends
    yunke_pull_friends.main()


def backfill_deal_cycle(dry_run=False):
    """补齐 orders.deal_cycle_days"""
    logger.info("=" * 50)
    logger.info("Step 2: 补齐 orders.deal_cycle_days")
    logger.info("=" * 50)

    # 1. 查缺 deal_cycle_days 的订单（有 wechat_id）
    result = supabase.table('orders').select(
        'id, wechat_id, order_date, customer_name, amount, order_stage'
    ).is_('deal_cycle_days', 'null').not_.is_('wechat_id', 'null').execute()

    orders = result.data
    logger.info(f"待补订单: {len(orders)}单")
    if not orders:
        logger.info("无需补数据")
        return

    # 2. 收集所有 wechat_id，批量查 contacts.add_time
    wechat_ids = list(set(o['wechat_id'] for o in orders if o.get('wechat_id')))
    logger.info(f"涉及 {len(wechat_ids)} 个独立 wechat_id")

    # 分批查 contacts（supabase 单次限制）
    add_time_map = {}
    batch_size = 50
    for i in range(0, len(wechat_ids), batch_size):
        batch = wechat_ids[i:i + batch_size]
        r = supabase.table('contacts').select(
            'wechat_id, add_time'
        ).in_('wechat_id', batch).not_.is_('add_time', 'null').execute()
        for c in r.data:
            # 一个 wechat_id 可能对应多个销售，取最早的 add_time
            wid = c['wechat_id']
            at = c['add_time']
            if wid not in add_time_map or at < add_time_map[wid]:
                add_time_map[wid] = at

    logger.info(f"从 contacts 查到 {len(add_time_map)} 个有 add_time 的记录")

    # 3. 逐单计算并更新
    updated = 0
    still_missing = 0
    negative = 0

    for o in orders:
        wid = o['wechat_id']
        order_date = o.get('order_date')
        add_time_str = add_time_map.get(wid)

        if not add_time_str or not order_date:
            still_missing += 1
            continue

        try:
            od = datetime.strptime(order_date, '%Y-%m-%d').date()
            at_str = str(add_time_str).split('T')[0]
            at = datetime.strptime(at_str, '%Y-%m-%d').date()
            diff = (od - at).days

            if diff < 0:
                negative += 1
                name = o.get('customer_name') or wid
                logger.debug(f"  负数周期: {name} order={order_date} add={at_str} diff={diff}")
                continue

            if dry_run:
                name = o.get('customer_name') or wid
                logger.info(
                    f"  [DRY-RUN] {name} | {order_date} - {at_str} = {diff}天 | "
                    f"{o.get('order_stage')} {o.get('amount')}"
                )
            else:
                supabase.table('orders').update({
                    'deal_cycle_days': diff
                }).eq('id', o['id']).execute()

            updated += 1

        except Exception as e:
            logger.warning(f"  计算失败 order_id={o['id']}: {e}")

    logger.info("=" * 50)
    logger.info(f"结果: 补齐 {updated}单, 仍缺add_time {still_missing}单, 负数跳过 {negative}单")
    if dry_run:
        logger.info("DRY-RUN 模式 — 未实际写入")
    logger.info("=" * 50)


def main():
    parser = argparse.ArgumentParser(description='补齐 orders.deal_cycle_days')
    parser.add_argument('--skip-sync', action='store_true', help='跳过好友同步，直接补')
    parser.add_argument('--dry-run', action='store_true', help='只看不写')
    args = parser.parse_args()

    if not args.skip_sync:
        sync_friends()

    backfill_deal_cycle(dry_run=args.dry_run)


if __name__ == '__main__':
    main()
