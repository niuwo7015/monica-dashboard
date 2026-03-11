#!/usr/bin/env python3
"""
S-003: Phase 1 规则引擎 — 生成每日跟进任务
- 扫描contacts表所有客户（按wechat_id关联，不依赖customer_id）
- 查chat_messages表获取最后互动信息
- 按规则生成daily_tasks
- 支持 --dry-run 模式（只输出不写库）

规则逻辑（Phase 1）：
  前置过滤：只扫描有≥1条非系统消息聊天记录的客户（排除僵尸号）
  R3: 有聊天记录但≥7天无任何互动 → reactivate, priority=3（最先检查，避免被R1/R2覆盖）
  R1: 客户发了消息但销售未回复（1-6天） → urgent_reply, priority=10
  R2: 最后一条是销售发的，客户沉默3-6天 → follow_up_silent, priority=5
  R4: 暂停 — contacts中无聊天记录的僵尸号跳过，等add_time数据可用后恢复新客触达
"""

import os
import sys
import argparse
import logging
from datetime import datetime, date, timezone
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

# ============ 销售微信号列表 ============
SALES_WECHAT_IDS = [
    'wxid_am3kdib9tt3722',   # 可欣(乐乐)
    'wxid_p03xoj66oss112',   # 小杰(jay)
    'wxid_cbk7hkyyp11t12',   # 霄剑(Chen)
    'wxid_aufah51bw9ok22',   # Fiona
    'wxid_idjldooyihpj22',   # 晴天喵
    'wxid_rxc39paqvic522',   # Joy
]

SALES_NAMES = {
    'wxid_am3kdib9tt3722': '可欣',
    'wxid_p03xoj66oss112': '小杰',
    'wxid_cbk7hkyyp11t12': '霄剑',
    'wxid_aufah51bw9ok22': 'Fiona',
    'wxid_idjldooyihpj22': '晴天喵',
    'wxid_rxc39paqvic522': 'Joy',
}

# ============ 规则阈值 ============
URGENT_REPLY_DAYS = 1      # R1: 客户消息未回复超过N天
FOLLOW_UP_SILENT_DAYS = 3  # R2: 销售发消息后客户沉默N天
REACTIVATE_DAYS = 7        # R3: 完全无互动N天
# R4: 无聊天记录的contacts → initial_contact


def fetch_all_contacts():
    """获取所有非删除的contacts（私聊好友，排除群聊和公众号）"""
    all_contacts = []
    page_size = 1000
    offset = 0

    while True:
        result = supabase.table('contacts').select(
            'wechat_id, sales_wechat_id, nickname, remark, customer_id'
        ).eq('is_deleted', 0).neq(
            'friend_type', 2  # 排除群聊
        ).range(offset, offset + page_size - 1).execute()

        if not result.data:
            break

        all_contacts.extend(result.data)
        if len(result.data) < page_size:
            break
        offset += page_size

    return all_contacts


def fetch_last_messages_for_sales(sales_wechat_id):
    """
    获取某个销售的所有私聊最后消息信息。
    返回 dict: {contact_wechat_id: {last_sent_at, last_sender_type, last_customer_msg_at, last_sales_msg_at}}

    按sent_at desc分页拉取，边拉边统计，每个contact只需要最新的客户消息和销售消息。
    当所有已见contact的stats都已完整（或达到上限）时提前结束。
    """
    contact_stats = {}
    incomplete = set()  # 还缺少customer或sales消息的wechat_id
    page_size = 1000
    offset = 0

    while True:
        result = supabase.table('chat_messages').select(
            'wechat_id, sender_type, sent_at'
        ).eq(
            'sales_wechat_id', sales_wechat_id
        ).eq(
            'is_system_msg', False
        ).not_.like('room_id', '%@chatroom').order(
            'sent_at', desc=True
        ).range(offset, offset + page_size - 1).execute()

        if not result.data:
            break

        for msg in result.data:
            wid = msg.get('wechat_id')
            if not wid:
                continue

            sent_at = msg.get('sent_at')
            sender_type = msg.get('sender_type')

            if wid not in contact_stats:
                contact_stats[wid] = {
                    'last_sent_at': sent_at,
                    'last_sender_type': sender_type,
                    'last_customer_msg_at': None,
                    'last_sales_msg_at': None,
                }
                incomplete.add(wid)

            stats = contact_stats[wid]

            if sender_type == 'customer' and stats['last_customer_msg_at'] is None:
                stats['last_customer_msg_at'] = sent_at
            elif sender_type == 'sales' and stats['last_sales_msg_at'] is None:
                stats['last_sales_msg_at'] = sent_at

            # 两种sender_type都有了，该contact完整
            if stats['last_customer_msg_at'] and stats['last_sales_msg_at']:
                incomplete.discard(wid)

        if len(result.data) < page_size:
            break
        offset += page_size

    return contact_stats


def parse_iso_date(iso_str):
    """ISO时间字符串转datetime"""
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return None


def days_since(iso_str, now=None):
    """计算距今天数"""
    dt = parse_iso_date(iso_str)
    if not dt:
        return None
    if now is None:
        now = datetime.now(tz=timezone.utc)
    # 确保时区一致
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    return delta.days


def apply_rules(contact, msg_stats, now):
    """
    对单个contact应用规则，返回匹配的任务列表。
    每个任务: {task_type, trigger_rule, priority}
    """
    tasks = []
    wechat_id = contact['wechat_id']

    if msg_stats is None:
        # R4: 无非系统消息聊天记录 → 跳过（僵尸号/供应商/同事）
        # 暂不生成initial_contact任务，等add_time数据可用后可恢复新客触达
        return tasks

    last_sent_at = msg_stats.get('last_sent_at')
    last_sender_type = msg_stats.get('last_sender_type')
    last_customer_msg_at = msg_stats.get('last_customer_msg_at')
    last_sales_msg_at = msg_stats.get('last_sales_msg_at')

    silence_days = days_since(last_sent_at, now)

    # R3: 有聊天记录但≥7天无任何互动 → 需要激活（优先于R1/R2，避免被覆盖）
    # 超过7天的对话已经"冷掉"，不再是urgent_reply或follow_up，而是reactivate
    if silence_days is not None and silence_days >= REACTIVATE_DAYS:
        tasks.append({
            'task_type': 'reactivate',
            'trigger_rule': f'R3: {silence_days}天无互动',
            'priority': 3,
        })
        return tasks

    # R1: 客户发了消息但销售未回复（最后一条是客户发的，且≥1天，<7天）
    if last_sender_type == 'customer' and silence_days is not None and silence_days >= URGENT_REPLY_DAYS:
        # 确认销售确实没有在客户消息之后回复
        customer_dt = parse_iso_date(last_customer_msg_at)
        sales_dt = parse_iso_date(last_sales_msg_at)
        if customer_dt and (sales_dt is None or sales_dt < customer_dt):
            tasks.append({
                'task_type': 'urgent_reply',
                'trigger_rule': f'R1: 客户消息未回复{silence_days}天',
                'priority': 10,
            })
            return tasks  # R1优先级最高，命中后不再匹配其他规则

    # R2: 销售发了消息后客户沉默≥3天（<7天）
    if last_sender_type == 'sales' and silence_days is not None and silence_days >= FOLLOW_UP_SILENT_DAYS:
        tasks.append({
            'task_type': 'follow_up_silent',
            'trigger_rule': f'R2: 客户沉默{silence_days}天（销售已跟进）',
            'priority': 5,
        })
        return tasks

    return tasks


def generate_tasks(dry_run=False):
    """主流程：扫描所有contacts，应用规则，生成daily_tasks"""
    today = date.today()
    now = datetime.now(tz=timezone.utc)
    task_date_str = today.isoformat()

    logger.info(f"开始生成每日任务: {task_date_str}")

    # 1. 获取所有contacts
    contacts = fetch_all_contacts()
    logger.info(f"contacts总数: {len(contacts)}")

    # 按销售微信号分组
    contacts_by_sales = defaultdict(list)
    for c in contacts:
        sales_wid = c.get('sales_wechat_id')
        if sales_wid:
            contacts_by_sales[sales_wid].append(c)

    # 2. 逐销售处理
    all_tasks = []
    stats = {
        'total_contacts': len(contacts),
        'contacts_with_chat': 0,
        'contacts_no_chat': 0,
        'tasks_generated': 0,
        'by_type': defaultdict(int),
        'by_sales': defaultdict(int),
    }

    for sales_wechat_id in SALES_WECHAT_IDS:
        sales_contacts = contacts_by_sales.get(sales_wechat_id, [])
        if not sales_contacts:
            logger.info(f"  {SALES_NAMES.get(sales_wechat_id, sales_wechat_id)}: 无contacts，跳过")
            continue

        # 获取该销售的聊天统计
        msg_stats_map = fetch_last_messages_for_sales(sales_wechat_id)
        logger.info(
            f"  {SALES_NAMES.get(sales_wechat_id, sales_wechat_id)}: "
            f"{len(sales_contacts)}个contacts, {len(msg_stats_map)}个有聊天记录"
        )

        for contact in sales_contacts:
            contact_wechat_id = contact['wechat_id']
            msg_stats = msg_stats_map.get(contact_wechat_id)

            if msg_stats:
                stats['contacts_with_chat'] += 1
            else:
                stats['contacts_no_chat'] += 1

            # 应用规则
            matched_tasks = apply_rules(contact, msg_stats, now)

            for task in matched_tasks:
                task_row = {
                    'contact_wechat_id': contact_wechat_id,
                    'sales_wechat_id': sales_wechat_id,
                    'customer_id': contact.get('customer_id'),
                    'task_date': task_date_str,
                    'task_type': task['task_type'],
                    'trigger_rule': task['trigger_rule'],
                    'priority': task['priority'],
                    'status': 'pending',
                }
                # 清理None值
                task_row = {k: v for k, v in task_row.items() if v is not None}
                all_tasks.append(task_row)

                stats['tasks_generated'] += 1
                stats['by_type'][task['task_type']] += 1
                stats['by_sales'][sales_wechat_id] += 1

    # 3. 输出统计
    logger.info("=" * 50)
    logger.info(f"扫描完成:")
    logger.info(f"  contacts总数: {stats['total_contacts']}")
    logger.info(f"  有聊天记录: {stats['contacts_with_chat']}")
    logger.info(f"  无聊天记录: {stats['contacts_no_chat']}")
    logger.info(f"  生成任务数: {stats['tasks_generated']}")
    logger.info(f"  按类型:")
    for task_type, count in sorted(stats['by_type'].items()):
        logger.info(f"    {task_type}: {count}")
    logger.info(f"  按销售:")
    for sales_wid, count in sorted(stats['by_sales'].items()):
        logger.info(f"    {SALES_NAMES.get(sales_wid, sales_wid)}: {count}")

    # 4. 写入数据库（或dry-run）
    if dry_run:
        logger.info("=" * 50)
        logger.info("DRY-RUN模式 — 不写入数据库")
        logger.info(f"以下 {len(all_tasks)} 条任务将被生成:")
        # 打印前20条样本
        for i, task in enumerate(all_tasks[:20]):
            name = ''
            # 尝试找到对应的contact nickname
            for c in contacts:
                if c['wechat_id'] == task.get('contact_wechat_id') and c['sales_wechat_id'] == task.get('sales_wechat_id'):
                    name = c.get('remark') or c.get('nickname') or ''
                    break
            logger.info(
                f"  [{i+1}] {SALES_NAMES.get(task.get('sales_wechat_id', ''), '?')} → "
                f"{name}({task.get('contact_wechat_id', '?')}) | "
                f"{task['task_type']} P{task['priority']} | {task.get('trigger_rule', '')}"
            )
        if len(all_tasks) > 20:
            logger.info(f"  ... 省略 {len(all_tasks) - 20} 条")
        return stats

    # 正式写入
    if all_tasks:
        # 批量upsert（用唯一约束去重）
        batch_size = 50
        written = 0
        for i in range(0, len(all_tasks), batch_size):
            batch = all_tasks[i:i + batch_size]
            try:
                supabase.table('daily_tasks').upsert(
                    batch,
                    on_conflict='task_date,contact_wechat_id,sales_wechat_id,task_type'
                ).execute()
                written += len(batch)
            except Exception as e:
                logger.error(f"批量写入失败 (batch {i//batch_size + 1}): {e}")
                # 降级逐条
                for row in batch:
                    try:
                        supabase.table('daily_tasks').upsert(
                            row,
                            on_conflict='task_date,contact_wechat_id,sales_wechat_id,task_type'
                        ).execute()
                        written += 1
                    except Exception as e2:
                        logger.warning(f"写入失败: {e2}")

        logger.info(f"写入完成: {written}/{len(all_tasks)} 条")

    return stats


def main():
    parser = argparse.ArgumentParser(description='Phase 1 规则引擎 — 生成每日跟进任务')
    parser.add_argument('--dry-run', action='store_true', help='只输出不写库')
    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info(f"S-003 Phase 1 规则引擎 {'(DRY-RUN)' if args.dry_run else ''}")

    stats = generate_tasks(dry_run=args.dry_run)

    logger.info("=" * 50)
    logger.info("完成")


if __name__ == '__main__':
    main()
