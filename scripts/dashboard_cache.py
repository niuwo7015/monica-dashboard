#!/usr/bin/env python3
"""
T-027b: Dashboard数据预计算缓存
每10分钟运行，将Dashboard所需数据预计算为JSON文件
前端直接读取JSON，避免跨境API延迟

输出: /var/www/monica-dashboard/api/dashboard.json
"""

import os
import sys
import json
import logging
from datetime import datetime, date, timedelta
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / '.env')

from supabase import create_client

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv('SUPABASE_URL', 'https://dieeejjzbhkpgxdhwlxf.supabase.co')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')
OUTPUT_DIR = '/var/www/monica-dashboard/api'

# 3 main sales (matches frontend MAIN_SALES)
CORE_IDS = [
    'wxid_am3kdib9tt3722',  # 可欣
    'wxid_p03xoj66oss112',  # 小杰
    'wxid_cbk7hkyyp11t12',  # 霄剑
]
SALES_NAMES = {
    'wxid_am3kdib9tt3722': '可欣',
    'wxid_p03xoj66oss112': '小杰',
    'wxid_cbk7hkyyp11t12': '霄剑',
    'wxid_aufah51bw9ok22': 'Fiona',
    'wxid_idjldooyihpj22': '晴天喵',
    'wxid_rxc39paqvic522': 'Joy',
}


def compute_presets():
    """计算所有时间预设的日期范围"""
    today = date.today()
    first_of_month = today.replace(day=1)
    if today.month == 1:
        last_month_first = date(today.year - 1, 12, 1)
    else:
        last_month_first = date(today.year, today.month - 1, 1)
    last_month_last = first_of_month - timedelta(days=1)

    return {
        'today': (today, today),
        '7d': (today - timedelta(days=6), today),
        '14d': (today - timedelta(days=13), today),
        '30d': (today - timedelta(days=29), today),
        '90d': (today - timedelta(days=89), today),
        'month': (first_of_month, today),
        'lastMonth': (last_month_first, last_month_last),
        # halfYear skipped: funnel RPC times out on 180+ day ranges
    }


def fetch_funnel_cohort(sb, start, end):
    """漏斗-按获客"""
    try:
        r = sb.rpc('dashboard_funnel_cohort', {
            'p_sales_ids': CORE_IDS,
            'p_start': start.isoformat(),
            'p_end': end.isoformat(),
        }).execute()
        if r.data:
            return {k: int(v) for k, v in r.data.items()}
    except Exception as e:
        logger.warning(f"funnel_cohort failed for {start}~{end}: {e}")
    return {'added': 0, 'conversation': 0, 'quote': 0, 'deposit': 0, 'won': 0}


def fetch_funnel_period(sb, start, end):
    """漏斗-按成交"""
    try:
        r = sb.rpc('dashboard_funnel_period', {
            'p_sales_ids': CORE_IDS,
            'p_start': start.isoformat(),
            'p_end': end.isoformat(),
        }).execute()
        if r.data:
            return {k: int(v) for k, v in r.data.items()}
    except Exception as e:
        logger.warning(f"funnel_period failed for {start}~{end}: {e}")
    return {'added': 0, 'conversation': 0, 'quote': 0, 'deposit': 0, 'won': 0}


def fetch_coverage(sb, start, end):
    """覆盖率"""
    try:
        all_data = []
        page_size = 1000
        offset = 0
        while True:
            r = sb.table('daily_tasks').select(
                'id, status'
            ).in_('sales_wechat_id', CORE_IDS
            ).gte('task_date', start.isoformat()
            ).lte('task_date', end.isoformat()
            ).range(offset, offset + page_size - 1).execute()
            batch = r.data or []
            all_data.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size

        total = len(all_data)
        done = sum(1 for t in all_data if t.get('status') == 'done')
        pct = round(done / total * 100) if total > 0 else 0
        return {'pct': pct, 'done': done, 'total': total, 'gap': total - done}
    except Exception as e:
        logger.warning(f"coverage failed: {e}")
        return {'pct': 0, 'done': 0, 'total': 0, 'gap': 0}


def fetch_performance(sb, start, end):
    """业绩统计"""
    try:
        # Fetch won orders with sales_wechat_id
        all_orders = []
        page_size = 1000
        offset = 0
        while True:
            q = sb.table('orders').select(
                'amount, wechat_id, order_date, deal_cycle_days, sales_wechat_id'
            ).eq('order_stage', 'won')
            if start:
                q = q.gte('order_date', start.isoformat())
            if end:
                q = q.lte('order_date', end.isoformat())
            r = q.range(offset, offset + page_size - 1).execute()
            batch = r.data or []
            all_orders.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size

        total_amount = sum(float(o.get('amount') or 0) for o in all_orders)
        total_orders = len(all_orders)
        avg_price = round(total_amount / total_orders) if total_orders > 0 else 0

        with_cycle = [o for o in all_orders if o.get('deal_cycle_days') is not None]
        avg_cycle = round(sum(o['deal_cycle_days'] for o in with_cycle) / len(with_cycle)) if with_cycle else None

        # Per-sales breakdown
        sales_agg = {}
        for o in all_orders:
            sid = o.get('sales_wechat_id') or 'unknown'
            if sid not in sales_agg:
                sales_agg[sid] = {'name': SALES_NAMES.get(sid, '未知'), 'amount': 0, 'count': 0, 'cycles': []}
            sales_agg[sid]['amount'] += float(o.get('amount') or 0)
            sales_agg[sid]['count'] += 1
            if o.get('deal_cycle_days') is not None:
                sales_agg[sid]['cycles'].append(o['deal_cycle_days'])

        breakdown = []
        for sid, v in sorted(sales_agg.items(), key=lambda x: x[1]['amount'], reverse=True):
            if sid == 'unknown':
                continue
            breakdown.append({
                'wechatId': sid,
                'name': v['name'],
                'amount': v['amount'],
                'count': v['count'],
                'avgCycle': round(sum(v['cycles']) / len(v['cycles'])) if v['cycles'] else None,
            })

        return {
            'totalAmount': total_amount,
            'totalOrders': total_orders,
            'avgUnitPrice': avg_price,
            'avgDealCycle': avg_cycle,
            'salesBreakdown': breakdown,
        }
    except Exception as e:
        logger.warning(f"performance failed: {e}")
        return {'totalAmount': 0, 'totalOrders': 0, 'avgUnitPrice': 0, 'avgDealCycle': None, 'salesBreakdown': []}


def fetch_follow_up(sb, start, end):
    """销售跟进率"""
    try:
        all_data = []
        page_size = 1000
        offset = 0
        while True:
            r = sb.table('daily_tasks').select(
                'sales_wechat_id, status'
            ).in_('sales_wechat_id', CORE_IDS
            ).gte('task_date', start.isoformat()
            ).lte('task_date', end.isoformat()
            ).range(offset, offset + page_size - 1).execute()
            batch = r.data or []
            all_data.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size

        sales_map = {}
        for sid in CORE_IDS:
            sales_map[sid] = {'name': SALES_NAMES.get(sid, sid), 'wechatId': sid, 'done': 0, 'total': 0}

        for t in all_data:
            sid = t.get('sales_wechat_id')
            if sid in sales_map:
                sales_map[sid]['total'] += 1
                if t.get('status') == 'done':
                    sales_map[sid]['done'] += 1

        result = []
        for s in sales_map.values():
            s['pct'] = round(s['done'] / s['total'] * 100) if s['total'] > 0 else 0
            result.append(s)
        return result
    except Exception as e:
        logger.warning(f"follow_up failed: {e}")
        return []


def fetch_risk_signals(sb):
    """风险信号Top10"""
    try:
        r = sb.rpc('dashboard_risk_top10', {'p_sales_ids': CORE_IDS}).execute()
        if r.data:
            return [
                {
                    'contactName': row.get('remark') or row.get('nickname') or row.get('wechat_id'),
                    'salesName': SALES_NAMES.get(row.get('sales_wechat_id'), '未知'),
                    'silenceDays': row.get('silence_days'),
                    'lastMessage': row.get('last_content'),
                    'lastMessageAt': row.get('last_sent_at'),
                    'followUpStatus': '已跟进' if row.get('task_status') == 'done' else '待跟进',
                }
                for row in r.data
            ]
    except Exception as e:
        logger.warning(f"risk_signals failed: {e}")
    return []


def main():
    if not SUPABASE_KEY:
        logger.error("SUPABASE_SERVICE_ROLE_KEY not set")
        sys.exit(1)

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    presets = compute_presets()

    logger.info("开始预计算Dashboard数据...")

    result = {
        'generated_at': datetime.now().isoformat(),
        'presets': {},
        'risk_signals': None,
    }

    # Risk signals (不依赖时间范围)
    logger.info("  计算风险信号...")
    result['risk_signals'] = fetch_risk_signals(sb)

    # 每个时间预设
    for key, (start, end) in presets.items():
        logger.info(f"  计算 {key} ({start} ~ {end})...")
        try:
            result['presets'][key] = {
                'dateRange': {'start': start.isoformat(), 'end': end.isoformat()},
                'coverage': fetch_coverage(sb, start, end),
                'funnelCohort': fetch_funnel_cohort(sb, start, end),
                'funnelPeriod': fetch_funnel_period(sb, start, end),
                'performance': fetch_performance(sb, start, end),
                'followUp': fetch_follow_up(sb, start, end),
            }
        except Exception as e:
            logger.error(f"  {key} 计算失败，跳过: {e}")

    # Write JSON
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, 'dashboard.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False)

    size_kb = os.path.getsize(output_path) / 1024
    logger.info(f"✅ 写入 {output_path} ({size_kb:.1f} KB)")
    logger.info(f"   包含 {len(result['presets'])} 个时间预设 + 风险信号")


if __name__ == '__main__':
    main()
