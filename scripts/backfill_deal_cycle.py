#!/usr/bin/env python3
"""
T-021: 补齐 orders 表 deal_cycle_days

成交周期定义（三段式成交）：
  1. 客户付1000看小样（deposit）
  2. 客户付订金确认订单（won）← 中段，算成交
  3. 付尾款发货

算法：
  deal_cycle_days = won订单的order_date - contacts.add_time（加微信日期）
  只有won订单才算成交周期，deposit订单不算

用法：
  python3 backfill_deal_cycle.py              # 补齐
  python3 backfill_deal_cycle.py --dry-run    # 只看不写
  python3 backfill_deal_cycle.py --reset      # 清除旧值后重算
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


def backfill_deal_cycle(dry_run=False, reset=False):
    """补齐 orders.deal_cycle_days（加微信 → 付订金确认）"""
    logger.info("=" * 50)
    logger.info("补齐 orders.deal_cycle_days")
    logger.info("算法: won订单的order_date - contacts.add_time（加微信日期）")
    logger.info("=" * 50)

    # 0. 如果reset，先清除所有旧值
    if reset:
        logger.info("--reset: 清除所有旧 deal_cycle_days")
        if not dry_run:
            supabase.table('orders').update(
                {'deal_cycle_days': None}
            ).not_.is_('deal_cycle_days', 'null').execute()

    # 1. 查需要补 deal_cycle_days 的 won 订单
    logger.info("Step 1: 查询需要补充的won订单...")
    won_orders = []
    offset = 0
    page_size = 1000
    while True:
        q = supabase.table('orders').select(
            'id, wechat_id, order_date, customer_name, amount'
        ).eq('order_stage', 'won')
        if not reset:
            q = q.is_('deal_cycle_days', 'null')
        q = q.not_.is_('wechat_id', 'null').range(offset, offset + page_size - 1)
        r = q.execute()
        won_orders.extend(r.data)
        if len(r.data) < page_size:
            break
        offset += page_size

    logger.info(f"  {len(won_orders)} 个won订单待处理")
    if not won_orders:
        logger.info("无需补数据")
        return

    # 2. 收集wechat_id，查contacts.add_time
    wechat_ids = list(set(o['wechat_id'] for o in won_orders if o.get('wechat_id')))
    logger.info(f"Step 2: 查询 {len(wechat_ids)} 个客户的加微信时间...")

    add_time_map = {}
    batch_size = 50
    for i in range(0, len(wechat_ids), batch_size):
        batch = wechat_ids[i:i + batch_size]
        r = supabase.table('contacts').select(
            'wechat_id, add_time'
        ).in_('wechat_id', batch).not_.is_('add_time', 'null').execute()
        for c in r.data:
            wid = c['wechat_id']
            at = c['add_time']
            # 同一客户取最早的add_time
            if wid not in add_time_map or at < add_time_map[wid]:
                add_time_map[wid] = at

    logger.info(f"  匹配到 {len(add_time_map)} 个有add_time的客户")

    # 3. 计算并更新
    updated = 0
    no_add_time = 0
    negative = 0

    for o in won_orders:
        wid = o['wechat_id']
        order_date = o.get('order_date')
        add_time_str = add_time_map.get(wid)

        if not add_time_str:
            no_add_time += 1
            continue

        if not order_date:
            continue

        try:
            od = datetime.strptime(order_date, '%Y-%m-%d').date()
            at_str = str(add_time_str).split('T')[0]
            at = datetime.strptime(at_str, '%Y-%m-%d').date()
            diff = (od - at).days

            if diff < 0:
                negative += 1
                name = o.get('customer_name') or wid
                logger.debug(f"  负数: {name} won={order_date} add={at_str} diff={diff}")
                continue

            if dry_run:
                name = o.get('customer_name') or wid
                logger.info(
                    f"  [DRY-RUN] {name} | {order_date} - {at_str} = {diff}天 | "
                    f"¥{o.get('amount')}"
                )
            else:
                supabase.table('orders').update({
                    'deal_cycle_days': diff
                }).eq('id', o['id']).execute()

            updated += 1

        except Exception as e:
            logger.warning(f"  计算失败 order_id={o['id']}: {e}")

    logger.info("=" * 50)
    logger.info(f"结果: 补齐 {updated} 单, 无add_time {no_add_time} 单, 负数跳过 {negative} 单")
    if dry_run:
        logger.info("DRY-RUN 模式 — 未实际写入")
    logger.info("=" * 50)


def main():
    parser = argparse.ArgumentParser(description='补齐 orders.deal_cycle_days（成交周期）')
    parser.add_argument('--dry-run', action='store_true', help='只看不写')
    parser.add_argument('--reset', action='store_true', help='清除旧值后全量重算')
    args = parser.parse_args()

    backfill_deal_cycle(dry_run=args.dry_run, reset=args.reset)


if __name__ == '__main__':
    main()
