#!/usr/bin/env python3
"""
S-006: 飞书Webhook推送脚本
- 每日任务汇总：按销售分组推送待跟进客户数量
- 系统异常告警：脚本异常时发送告警消息
- 通过飞书自定义机器人Webhook推送

环境变量：
    FEISHU_WEBHOOK_URL     飞书机器人Webhook地址
    SUPABASE_URL           Supabase URL
    SUPABASE_SERVICE_ROLE_KEY  Supabase Service Role Key
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime, date
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / '.env')

import requests
from supabase import create_client

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ── 环境变量 ──────────────────────────────────────────────
FEISHU_WEBHOOK_URL = os.getenv('FEISHU_WEBHOOK_URL', '')
SUPABASE_URL = os.getenv('SUPABASE_URL', 'https://dieeejjzbhkpgxdhwlxf.supabase.co')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')

# ── 销售名称映射 ──────────────────────────────────────────
SALES_NAMES = {
    'wxid_am3kdib9tt3722': '可欣',
    'wxid_p03xoj66oss112': '小杰',
    'wxid_cbk7hkyyp11t12': '霄剑',
    'wxid_aufah51bw9ok22': 'Fiona',
    'wxid_idjldooyihpj22': '晴天喵',
    'wxid_rxc39paqvic522': 'Joy',
}

# ── 任务类型中文名 ────────────────────────────────────────
TASK_TYPE_NAMES = {
    'urgent_reply': '紧急回复',
    'follow_up_silent': '沉默跟进',
    'reactivate': '重新激活',
    'initial_contact': '首次联系',
}

# ── 优先级排序（高优先级在前）───────────────────────────────
TASK_TYPE_PRIORITY = {
    'urgent_reply': 1,
    'follow_up_silent': 2,
    'reactivate': 3,
    'initial_contact': 4,
}


def send_feishu_message(webhook_url, msg_type, content):
    """发送飞书消息

    Args:
        webhook_url: Webhook地址
        msg_type: 消息类型 (text / interactive)
        content: 消息内容
    Returns:
        bool: 是否发送成功
    """
    if msg_type == 'text':
        payload = {
            "msg_type": "text",
            "content": {"text": content}
        }
    elif msg_type == 'interactive':
        payload = {
            "msg_type": "interactive",
            "card": content
        }
    else:
        logger.error(f"不支持的消息类型: {msg_type}")
        return False

    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        if result.get('code') == 0 or result.get('StatusCode') == 0:
            logger.info("飞书消息发送成功")
            return True
        else:
            logger.error(f"飞书返回错误: {result}")
            return False
    except Exception as e:
        logger.error(f"飞书消息发送失败: {e}")
        return False


def fetch_today_tasks(supabase, task_date):
    """获取指定日期的daily_tasks"""
    try:
        result = supabase.table('daily_tasks').select(
            'sales_wechat_id, task_type, priority, status, contact_wechat_id'
        ).eq('task_date', task_date.isoformat()).execute()
        return result.data or []
    except Exception as e:
        logger.error(f"查询daily_tasks失败: {e}")
        return []


def build_daily_summary_card(task_date, tasks):
    """构建每日任务汇总的飞书卡片消息"""

    # 按销售分组
    by_sales = defaultdict(lambda: defaultdict(int))
    total_by_type = defaultdict(int)

    for task in tasks:
        sales_id = task.get('sales_wechat_id', 'unknown')
        task_type = task.get('task_type', 'unknown')
        by_sales[sales_id][task_type] += 1
        total_by_type[task_type] += 1

    total_tasks = len(tasks)
    pending_tasks = sum(1 for t in tasks if t.get('status') == 'pending')

    # 构建卡片元素
    elements = []

    # 总览
    overview_parts = []
    for tt in sorted(total_by_type.keys(), key=lambda x: TASK_TYPE_PRIORITY.get(x, 99)):
        name = TASK_TYPE_NAMES.get(tt, tt)
        count = total_by_type[tt]
        overview_parts.append(f"{name}: {count}")

    elements.append({
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": f"**总任务数**: {total_tasks}　|　**待处理**: {pending_tasks}\n" +
                       "　".join(overview_parts)
        }
    })

    elements.append({"tag": "hr"})

    # 每个销售的明细
    for sales_id in sorted(by_sales.keys(),
                           key=lambda x: sum(by_sales[x].values()), reverse=True):
        sales_name = SALES_NAMES.get(sales_id, sales_id[:8])
        type_counts = by_sales[sales_id]
        total = sum(type_counts.values())

        details = []
        for tt in sorted(type_counts.keys(), key=lambda x: TASK_TYPE_PRIORITY.get(x, 99)):
            name = TASK_TYPE_NAMES.get(tt, tt)
            details.append(f"{name} {type_counts[tt]}")

        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**{sales_name}**　共 {total} 条　|　{'　'.join(details)}"
            }
        })

    # 底部备注
    elements.append({"tag": "hr"})
    elements.append({
        "tag": "note",
        "elements": [{
            "tag": "plain_text",
            "content": f"Monica销售AI · 每日任务汇总 · {task_date.isoformat()}"
        }]
    })

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"📋 每日跟进任务 · {task_date.strftime('%m月%d日')}"
            },
            "template": "blue"
        },
        "elements": elements
    }

    return card


def build_daily_summary_text(task_date, tasks):
    """构建纯文本版每日任务汇总（作为卡片消息的降级方案）"""

    by_sales = defaultdict(lambda: defaultdict(int))
    total_tasks = len(tasks)
    pending_tasks = sum(1 for t in tasks if t.get('status') == 'pending')

    for task in tasks:
        sales_id = task.get('sales_wechat_id', 'unknown')
        task_type = task.get('task_type', 'unknown')
        by_sales[sales_id][task_type] += 1

    lines = [
        f"📋 每日跟进任务 · {task_date.strftime('%m月%d日')}",
        f"总任务数: {total_tasks} | 待处理: {pending_tasks}",
        "─" * 30,
    ]

    for sales_id in sorted(by_sales.keys(),
                           key=lambda x: sum(by_sales[x].values()), reverse=True):
        sales_name = SALES_NAMES.get(sales_id, sales_id[:8])
        type_counts = by_sales[sales_id]
        total = sum(type_counts.values())

        details = []
        for tt in sorted(type_counts.keys(), key=lambda x: TASK_TYPE_PRIORITY.get(x, 99)):
            name = TASK_TYPE_NAMES.get(tt, tt)
            details.append(f"{name}({type_counts[tt]})")

        lines.append(f"  {sales_name}: {total}条 [{', '.join(details)}]")

    lines.append("─" * 30)
    lines.append(f"Monica销售AI · {task_date.isoformat()}")

    return "\n".join(lines)


def send_daily_summary(task_date=None, dry_run=False):
    """发送每日任务汇总"""

    if not SUPABASE_KEY:
        logger.error("SUPABASE_SERVICE_ROLE_KEY 环境变量未设置")
        return False

    if not FEISHU_WEBHOOK_URL and not dry_run:
        logger.error("FEISHU_WEBHOOK_URL 环境变量未设置")
        return False

    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    if task_date is None:
        task_date = date.today()

    logger.info(f"查询 {task_date} 的每日任务...")
    tasks = fetch_today_tasks(supabase, task_date)

    if not tasks:
        logger.info("今日无任务，跳过推送")
        return True

    logger.info(f"共 {len(tasks)} 条任务")

    # 优先发卡片，失败则降级文本
    card = build_daily_summary_card(task_date, tasks)

    if dry_run:
        logger.info("=== DRY RUN: 卡片消息预览 ===")
        text = build_daily_summary_text(task_date, tasks)
        print(text)
        print(f"\n卡片JSON长度: {len(json.dumps(card, ensure_ascii=False))} 字符")
        return True

    ok = send_feishu_message(FEISHU_WEBHOOK_URL, 'interactive', card)
    if not ok:
        logger.warning("卡片消息发送失败，尝试纯文本...")
        text = build_daily_summary_text(task_date, tasks)
        ok = send_feishu_message(FEISHU_WEBHOOK_URL, 'text', text)

    return ok


def send_alert(title, detail, level='warning'):
    """发送系统异常告警

    Args:
        title: 告警标题
        detail: 告警详情
        level: 告警级别 (info / warning / error)
    """
    if not FEISHU_WEBHOOK_URL:
        logger.error("FEISHU_WEBHOOK_URL 环境变量未设置，无法发送告警")
        return False

    color_map = {'info': 'blue', 'warning': 'orange', 'error': 'red'}
    icon_map = {'info': 'ℹ️', 'warning': '⚠️', 'error': '🚨'}

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"{icon_map.get(level, '⚠️')} {title}"
            },
            "template": color_map.get(level, 'orange')
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": detail
                }
            },
            {"tag": "hr"},
            {
                "tag": "note",
                "elements": [{
                    "tag": "plain_text",
                    "content": f"Monica销售AI · 系统告警 · {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                }]
            }
        ]
    }

    return send_feishu_message(FEISHU_WEBHOOK_URL, 'interactive', card)


def main():
    parser = argparse.ArgumentParser(description='飞书Webhook推送')
    parser.add_argument('--dry-run', action='store_true', help='预览消息内容，不实际发送')
    parser.add_argument('--date', type=str, help='指定日期 (YYYY-MM-DD)，默认今天')
    parser.add_argument('--alert', type=str, help='发送告警消息')
    parser.add_argument('--alert-detail', type=str, default='', help='告警详情')
    parser.add_argument('--alert-level', type=str, default='warning',
                        choices=['info', 'warning', 'error'], help='告警级别')
    args = parser.parse_args()

    if args.alert:
        ok = send_alert(args.alert, args.alert_detail, args.alert_level)
        sys.exit(0 if ok else 1)

    task_date = None
    if args.date:
        task_date = date.fromisoformat(args.date)

    ok = send_daily_summary(task_date=task_date, dry_run=args.dry_run)
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
