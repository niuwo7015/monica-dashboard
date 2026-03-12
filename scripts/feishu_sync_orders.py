#!/usr/bin/env python3
"""
S-006: 飞书在线表格订单同步脚本
- 通过飞书Open API读取订单表格数据
- 同步到Supabase orders表
- 支持增量同步（基于feishu_row_id去重）

环境变量：
    FEISHU_APP_ID              飞书应用App ID
    FEISHU_APP_SECRET          飞书应用App Secret
    FEISHU_SPREADSHEET_TOKEN   飞书电子表格token（从URL获取）
    FEISHU_SHEET_ID            工作表ID（可选，默认读第一个sheet）
    SUPABASE_URL               Supabase URL
    SUPABASE_SERVICE_ROLE_KEY  Supabase Service Role Key

飞书表格预期列结构（可通过COLUMN_MAP配置映射）：
    A列: 客户微信号 (customer_wechat_id)
    B列: 客户姓名/备注名
    C列: 下单日期 (order_date)
    D列: 订单金额 (amount)
    E列: 产品线 (product_line)
    F列: 负责销售 (sales_name)
    G列: 备注 (remark)
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime, date
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
FEISHU_APP_ID = os.getenv('FEISHU_APP_ID', '')
FEISHU_APP_SECRET = os.getenv('FEISHU_APP_SECRET', '')
FEISHU_SPREADSHEET_TOKEN = os.getenv('FEISHU_SPREADSHEET_TOKEN', '')
FEISHU_SHEET_ID = os.getenv('FEISHU_SHEET_ID', '')

SUPABASE_URL = os.getenv('SUPABASE_URL', 'https://dieeejjzbhkpgxdhwlxf.supabase.co')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')

FEISHU_API_BASE = 'https://open.feishu.cn/open-apis'

# ── 销售名称→微信号映射（反查） ───────────────────────────
SALES_NAME_TO_WECHAT = {
    '可欣': 'wxid_am3kdib9tt3722',
    '乐乐': 'wxid_am3kdib9tt3722',
    '小杰': 'wxid_p03xoj66oss112',
    'jay': 'wxid_p03xoj66oss112',
    '霄剑': 'wxid_cbk7hkyyp11t12',
    'Chen': 'wxid_cbk7hkyyp11t12',
    'Fiona': 'wxid_aufah51bw9ok22',
    'fiona': 'wxid_aufah51bw9ok22',
    '晴天喵': 'wxid_idjldooyihpj22',
    'Joy': 'wxid_rxc39paqvic522',
    'joy': 'wxid_rxc39paqvic522',
}

# ── 列映射配置（飞书表格列号 → 字段名） ──────────────────
# 列号从0开始，根据实际表格调整
COLUMN_MAP = {
    0: 'customer_wechat_id',   # A列：客户微信号
    1: 'customer_name',        # B列：客户姓名（不入库，仅日志用）
    2: 'order_date',           # C列：下单日期
    3: 'amount',               # D列：订单金额
    4: 'product_line',         # E列：产品线
    5: 'sales_name',           # F列：负责销售
    6: 'remark',               # G列：备注
}


def get_tenant_access_token():
    """获取飞书 tenant_access_token"""
    url = f'{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal'
    payload = {
        'app_id': FEISHU_APP_ID,
        'app_secret': FEISHU_APP_SECRET,
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get('code') == 0:
            token = data.get('tenant_access_token')
            expire = data.get('expire', 0)
            logger.info(f"获取tenant_access_token成功，有效期 {expire}s")
            return token
        else:
            logger.error(f"获取token失败: {data.get('msg')}")
            return None
    except Exception as e:
        logger.error(f"获取token异常: {e}")
        return None


def get_sheet_id(token, spreadsheet_token):
    """获取电子表格的第一个工作表ID"""
    url = f'{FEISHU_API_BASE}/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/query'
    headers = {'Authorization': f'Bearer {token}'}

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get('code') == 0:
            sheets = data.get('data', {}).get('sheets', [])
            if sheets:
                sheet_id = sheets[0].get('sheet_id')
                title = sheets[0].get('title', '')
                logger.info(f"工作表: {title} (ID: {sheet_id})")
                return sheet_id
        logger.error(f"获取工作表失败: {data}")
        return None
    except Exception as e:
        logger.error(f"获取工作表异常: {e}")
        return None


def read_spreadsheet(token, spreadsheet_token, sheet_id):
    """读取飞书电子表格数据"""
    # 读取范围：整个工作表（飞书API会自动裁剪到有数据的区域）
    range_str = f'{sheet_id}'
    url = (f'{FEISHU_API_BASE}/sheets/v2/spreadsheets/{spreadsheet_token}'
           f'/values/{range_str}')
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }
    params = {
        'valueRenderOption': 'ToString',
        'dateTimeRenderOption': 'FormattedString',
    }

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get('code') == 0:
            values = data.get('data', {}).get('valueRange', {}).get('values', [])
            logger.info(f"读取到 {len(values)} 行数据（含表头）")
            return values
        else:
            logger.error(f"读取表格失败: code={data.get('code')}, msg={data.get('msg')}")
            return None
    except Exception as e:
        logger.error(f"读取表格异常: {e}")
        return None


def parse_date(value):
    """解析日期字段，支持多种格式"""
    if not value:
        return None
    value = str(value).strip()

    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d', '%m/%d/%Y', '%Y年%m月%d日'):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue

    # 尝试纯数字（Excel序列号，飞书有时也用这个）
    try:
        serial = float(value)
        if 40000 < serial < 50000:
            from datetime import timedelta
            base = datetime(1899, 12, 30)
            return (base + timedelta(days=int(serial))).date().isoformat()
    except (ValueError, TypeError):
        pass

    logger.warning(f"无法解析日期: '{value}'")
    return None


def parse_amount(value):
    """解析金额字段"""
    if not value:
        return None
    value = str(value).strip().replace(',', '').replace('¥', '').replace('￥', '')
    try:
        return float(value)
    except (ValueError, TypeError):
        logger.warning(f"无法解析金额: '{value}'")
        return None


def parse_rows(rows):
    """将表格行解析为订单记录"""
    if not rows or len(rows) < 2:
        logger.warning("表格数据不足（无数据行）")
        return []

    # 第一行是表头，跳过
    header = rows[0]
    logger.info(f"表头: {header}")

    orders = []
    skipped = 0

    for row_idx, row in enumerate(rows[1:], start=2):
        # 按 COLUMN_MAP 提取字段
        raw = {}
        for col_idx, field_name in COLUMN_MAP.items():
            raw[field_name] = row[col_idx] if col_idx < len(row) else None

        # 客户微信号必填
        wechat_id = str(raw.get('customer_wechat_id', '') or '').strip()
        if not wechat_id:
            skipped += 1
            continue

        # 解析日期
        order_date = parse_date(raw.get('order_date'))
        if not order_date:
            logger.warning(f"第{row_idx}行日期无效，跳过: {raw.get('order_date')}")
            skipped += 1
            continue

        # 解析金额
        amount = parse_amount(raw.get('amount'))

        # 销售名称→微信号
        sales_name = str(raw.get('sales_name', '') or '').strip()
        sales_wechat_id = SALES_NAME_TO_WECHAT.get(sales_name)

        # 构建订单记录
        order = {
            'customer_wechat_id': wechat_id,
            'order_date': order_date,
            'amount': amount,
            'product_line': str(raw.get('product_line', '') or '').strip() or None,
            'sales_wechat_id': sales_wechat_id,
            'remark': str(raw.get('remark', '') or '').strip() or None,
            'feishu_row_id': f"row_{row_idx}",  # 用行号作为去重ID
            'order_status': 'completed',
            'synced_at': datetime.utcnow().isoformat(),
        }

        orders.append(order)

    logger.info(f"解析完成: {len(orders)}条有效订单, {skipped}条跳过")
    return orders


def sync_to_supabase(supabase, orders):
    """批量写入Supabase orders表"""
    if not orders:
        logger.info("无订单需要同步")
        return 0

    written = 0
    batch_size = 50

    for i in range(0, len(orders), batch_size):
        batch = orders[i:i + batch_size]
        try:
            supabase.table('orders').upsert(
                batch,
                on_conflict='feishu_row_id'
            ).execute()
            written += len(batch)
            logger.info(f"写入 {written}/{len(orders)} 条")
        except Exception as e:
            logger.error(f"批量写入失败: {e}")
            # 降级逐条写入
            for row in batch:
                try:
                    supabase.table('orders').upsert(
                        row,
                        on_conflict='feishu_row_id'
                    ).execute()
                    written += 1
                except Exception as e2:
                    logger.warning(f"单条写入失败 (wechat={row.get('customer_wechat_id')}): {e2}")

    logger.info(f"同步完成: 共写入 {written}/{len(orders)} 条订单")
    return written


def main():
    parser = argparse.ArgumentParser(description='飞书订单表格同步')
    parser.add_argument('--dry-run', action='store_true', help='只读取和解析，不写入数据库')
    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info("S-006: 飞书订单同步开始")
    logger.info("=" * 50)

    # 检查环境变量
    missing = []
    if not FEISHU_APP_ID:
        missing.append('FEISHU_APP_ID')
    if not FEISHU_APP_SECRET:
        missing.append('FEISHU_APP_SECRET')
    if not FEISHU_SPREADSHEET_TOKEN:
        missing.append('FEISHU_SPREADSHEET_TOKEN')
    if not SUPABASE_KEY:
        missing.append('SUPABASE_SERVICE_ROLE_KEY')

    if missing:
        logger.error(f"缺少环境变量: {', '.join(missing)}")
        sys.exit(1)

    # 1. 获取飞书访问令牌
    token = get_tenant_access_token()
    if not token:
        logger.error("无法获取飞书访问令牌，退出")
        # 发送告警（如果webhook已配置）
        try:
            from feishu_notify import send_alert
            send_alert('订单同步失败', '无法获取飞书访问令牌，请检查FEISHU_APP_ID/SECRET配置', 'error')
        except Exception:
            pass
        sys.exit(1)

    # 2. 确定工作表ID
    sheet_id = FEISHU_SHEET_ID
    if not sheet_id:
        sheet_id = get_sheet_id(token, FEISHU_SPREADSHEET_TOKEN)
        if not sheet_id:
            logger.error("无法获取工作表ID，退出")
            sys.exit(1)

    # 3. 读取表格数据
    rows = read_spreadsheet(token, FEISHU_SPREADSHEET_TOKEN, sheet_id)
    if rows is None:
        logger.error("读取表格数据失败，退出")
        sys.exit(1)

    # 4. 解析订单
    orders = parse_rows(rows)

    if args.dry_run:
        logger.info("=== DRY RUN: 解析结果预览 ===")
        for i, order in enumerate(orders[:10]):
            print(f"  [{i+1}] {order['customer_wechat_id']} | "
                  f"{order['order_date']} | "
                  f"¥{order['amount'] or '?'} | "
                  f"{order['product_line'] or '-'} | "
                  f"{order['sales_wechat_id'] or '-'}")
        if len(orders) > 10:
            print(f"  ... 共 {len(orders)} 条")
        return

    # 5. 写入Supabase
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    written = sync_to_supabase(supabase, orders)

    logger.info("=" * 50)
    logger.info(f"同步完成: {written} 条订单已写入orders表")
    logger.info("=" * 50)

    # 同步完成后发送通知（可选）
    if written > 0:
        try:
            from feishu_notify import send_alert
            send_alert(
                '订单数据同步完成',
                f'从飞书表格同步了 {written} 条订单数据到系统',
                'info'
            )
        except Exception:
            pass


if __name__ == '__main__':
    main()
