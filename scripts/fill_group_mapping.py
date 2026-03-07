#!/usr/bin/env python3
"""
自动填充group_customer_mapping表

1. 从chat_messages中找所有群聊消息（room_id不为空的记录）
2. 提取去重的(room_id, wechat_id)组合——即哪些人在哪些群里发过言
3. 过滤掉销售自己的微信号（6个已知销售号）
4. 用wechat_id去contacts表匹配，拿customer_id
5. 从contacts表拉群名（friend_type=2，wechat_id=群ID的记录的nickname字段）
6. 写入group_customer_mapping表，upsert去重
"""

import os
import sys
import logging
from datetime import datetime

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

# ============ 销售微信号（排除用） ============
SALES_WECHAT_IDS = {
    'wxid_am3kdib9tt3722',
    'wxid_p03xoj66oss112',
    'wxid_cbk7hkyyp11t12',
    'wxid_aufah51bw9ok22',
    'wxid_idjldooyihpj22',
    'wxid_rxc39paqvic522',
}


def fetch_group_messages(page_size=1000):
    """分页获取所有群聊消息（room_id不为空）"""
    all_data = []
    offset = 0
    while True:
        result = supabase.table('chat_messages').select(
            'room_id,wechat_id,sales_id'
        ).not_.is_('room_id', 'null').range(offset, offset + page_size - 1).execute()
        if not result.data:
            break
        all_data.extend(result.data)
        if len(result.data) < page_size:
            break
        offset += page_size
    return all_data


def main():
    logger.info("=" * 50)
    logger.info("开始填充 group_customer_mapping")

    # Step 1: 获取所有群聊消息的 room_id + wechat_id
    logger.info("Step 1: 从chat_messages获取群聊消息...")
    group_msgs = fetch_group_messages()
    logger.info(f"  群聊消息总数: {len(group_msgs)}")

    # Step 2: 提取去重的 (room_id, wechat_id) 组合
    room_members = {}  # room_id -> set of wechat_ids
    room_sales_ids = {}  # room_id -> set of sales_id (UUID)
    for msg in group_msgs:
        rid = msg.get('room_id')
        wid = msg.get('wechat_id')
        sid = msg.get('sales_id')
        if not rid or not wid:
            continue
        if rid not in room_members:
            room_members[rid] = set()
        room_members[rid].add(wid)
        if sid:
            if rid not in room_sales_ids:
                room_sales_ids[rid] = set()
            room_sales_ids[rid].add(sid)

    total_combos = sum(len(v) for v in room_members.values())
    logger.info(f"  去重后: {len(room_members)}个群, {total_combos}个(群,人)组合")

    # Step 3: 过滤掉销售微信号
    customer_combos = []  # list of (room_id, customer_wechat_id)
    sales_in_rooms = {}  # room_id -> set of sales wechat_ids found in messages
    for rid, members in room_members.items():
        sales_in_rooms[rid] = members & SALES_WECHAT_IDS
        customers = members - SALES_WECHAT_IDS
        for cid in customers:
            customer_combos.append((rid, cid))

    logger.info(f"  过滤销售后: {len(customer_combos)}个客户-群组合")

    # Step 4: 用wechat_id去contacts表匹配customer_id
    logger.info("Step 4: 从contacts表匹配customer_id...")
    # 获取所有相关的customer wechat_ids
    unique_customer_wids = set(c[1] for c in customer_combos)
    wechat_to_customer = {}  # wechat_id -> customer_id (contacts.id)

    # 分批查询（避免query过长）
    wid_list = list(unique_customer_wids)
    batch_size = 50
    for i in range(0, len(wid_list), batch_size):
        batch = wid_list[i:i+batch_size]
        # 查询contacts表
        result = supabase.table('contacts').select('id,wechat_id').in_('wechat_id', batch).execute()
        for row in (result.data or []):
            wechat_to_customer[row['wechat_id']] = row['id']

    matched = sum(1 for wid in unique_customer_wids if wid in wechat_to_customer)
    logger.info(f"  {matched}/{len(unique_customer_wids)}个客户微信号匹配到customer_id")

    # Step 5: 从contacts表拉群名
    logger.info("Step 5: 获取群名...")
    unique_rooms = list(room_members.keys())
    room_names = {}  # room_id -> group_name
    room_sales_wechat = {}  # room_id -> sales_wechat_id (from contacts)

    for i in range(0, len(unique_rooms), batch_size):
        batch = unique_rooms[i:i+batch_size]
        result = supabase.table('contacts').select(
            'wechat_id,nickname,sales_wechat_id'
        ).eq('friend_type', 2).in_('wechat_id', batch).execute()
        for row in (result.data or []):
            room_names[row['wechat_id']] = row.get('nickname', '')
            room_sales_wechat[row['wechat_id']] = row.get('sales_wechat_id', '')

    logger.info(f"  {len(room_names)}/{len(unique_rooms)}个群匹配到群名")

    # Step 6: 写入group_customer_mapping表
    logger.info("Step 6: 写入group_customer_mapping...")
    insert_count = 0
    update_count = 0
    error_count = 0

    for room_id, customer_wechat_id in customer_combos:
        customer_id = wechat_to_customer.get(customer_wechat_id)
        group_name = room_names.get(room_id, '')

        # 确定sales_wechat_id: 优先从contacts表获取，其次从群消息中找到的销售号
        sales_wid = room_sales_wechat.get(room_id, '')
        if not sales_wid and room_id in sales_in_rooms:
            # 取第一个出现的销售号
            sales_wid = next(iter(sales_in_rooms[room_id]), '')

        row = {
            'group_wechat_id': room_id,
            'customer_wechat_id': customer_wechat_id,
            'customer_id': customer_id,
            'group_name': group_name,
            'sales_wechat_id': sales_wid,
        }

        try:
            # 先查是否已存在（唯一约束: group_wechat_id + customer_wechat_id）
            existing = supabase.table('group_customer_mapping').select('id').eq(
                'group_wechat_id', room_id
            ).eq('customer_wechat_id', customer_wechat_id).execute()

            if existing.data:
                # 已存在则更新
                supabase.table('group_customer_mapping').update(row).eq(
                    'group_wechat_id', room_id
                ).eq('customer_wechat_id', customer_wechat_id).execute()
                update_count += 1
            else:
                # 不存在则插入
                supabase.table('group_customer_mapping').insert(row).execute()
                insert_count += 1
        except Exception as e:
            error_count += 1
            if error_count <= 5:
                logger.warning(f"写入失败 group={room_id}, customer={customer_wechat_id}: {e}")

    logger.info(f"写入完成: 新增 {insert_count}, 更新 {update_count}, 失败 {error_count}")
    logger.info("=" * 50)


if __name__ == '__main__':
    main()
