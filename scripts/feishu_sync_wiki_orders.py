#!/usr/bin/env python3
"""
T-016: 飞书wiki表格订单同步脚本
- 通过飞书wiki API获取文档节点的底层spreadsheet token
- 读取2026年订单数据并同步到Supabase orders表
- 支持增量同步（基于feishu_record_id去重）
- 自动判断order_stage（deposit/won）

环境变量：
    FEISHU_APP_ID              飞书应用App ID
    FEISHU_APP_SECRET          飞书应用App Secret
    SUPABASE_URL               Supabase URL
    SUPABASE_SERVICE_ROLE_KEY  Supabase Service Role Key

飞书wiki表格列结构（3个表格统一）：
    A(0):  下单期        → order_date
    B(1):  客服          → sales_id (通过users表映射)
    D(3):  微信号        → wechat_id
    J(9):  产品类型      → product
    K(10): 产品品名      → product (追加)
    P(15): 销售金额      → amount
    R(17): 订金备注      → deposit (解析金额)
    S(18): 尾款备注      → balance (解析金额)
    T(19): 下单时间      → (备用日期)
    U(20): 确认收款      → payment_status
    Z(25): 备注          → notes
"""

import os
import re
import sys
import json
import logging
import argparse
from datetime import datetime, timedelta, timezone

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
SUPABASE_URL = os.getenv('SUPABASE_URL', 'https://dieeejjzbhkpgxdhwlxf.supabase.co')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')

FEISHU_API_BASE = 'https://open.feishu.cn/open-apis'

# ── wiki表格配置 ──────────────────────────────────────────
# wiki node_token → 需要通过get_node获取底层spreadsheet obj_token
WIKI_NODE_TOKEN = 'H2wswEhJuioJzLk5YA5cBx3bncd'

# 也支持同步普通sheets表格（已有的2025数据表）
EXTRA_SPREADSHEET_TOKENS = os.getenv('FEISHU_SPREADSHEET_TOKENS', '').split(',')

# ── 客服名→users表sales_id映射 ────────────────────────────
SALES_NAME_TO_ID = {
    '小杰': '7bc7d8a0-85e7-492d-b50c-677492411089',
    'jay': '7bc7d8a0-85e7-492d-b50c-677492411089',
    'Jay': '7bc7d8a0-85e7-492d-b50c-677492411089',
    '可欣': '3c67cb66-6104-401d-b80a-0dff605871b5',
    '乐乐': '3c67cb66-6104-401d-b80a-0dff605871b5',
    '霄剑': 'a8490e00-d1ca-41dc-afe8-39bbb31138ae',
    '陈霄剑': 'a8490e00-d1ca-41dc-afe8-39bbb31138ae',
    'Chen': 'a8490e00-d1ca-41dc-afe8-39bbb31138ae',
}

# ── 列映射（与3个飞书表格统一结构对应） ──────────────────
COL_ORDER_DATE = 0       # A: 下单期
COL_SALES_NAME = 1       # B: 客服
COL_CUSTOMER_NAME = 2    # C: 博主          → customer_name
COL_WECHAT_ID = 3        # D: 微信号
COL_TAOBAO_ID = 5        # F: 旺旺号        → taobao_id
COL_RECEIVER_NAME = 6    # G: 收货人        → receiver_name
COL_PHONE = 7            # H: 电话          → phone
COL_ADDRESS = 8          # I: 地址          → address
COL_PRODUCT_TYPE = 9     # J: 产品类型
COL_PRODUCT_NAME = 10    # K: 产品品名
COL_SIZE = 11            # L: 尺寸（米）    → size
COL_SIDES = 12           # M: 单面/双面     → sides
COL_FABRIC = 13          # N: 面料          → fabric
COL_REQ_DETAIL = 14      # O: 需求明细      → requirement_detail
COL_AMOUNT = 15          # P: 销售金额
COL_PAY_CHANNEL = 16     # Q: 收款渠道      → payment_channel
COL_DEPOSIT_NOTE = 17    # R: 订金备注
COL_BALANCE_NOTE = 18    # S: 尾款备注
COL_ORDER_TIME = 19      # T: 下单时间（备用日期）
COL_PAYMENT_STATUS = 20  # U: 确认收款
COL_MANUFACTURER = 21    # V: 厂家          → manufacturer
COL_PROD_STATUS = 22     # W: 是否完成生产  → production_status
COL_SHIPPING_DATE = 23   # X: 发货日期      → shipping_date
COL_LOGISTICS = 24       # Y: 物流公司      → logistics_company
COL_NOTES = 25           # Z: 备注


def get_tenant_access_token():
    """获取飞书 tenant_access_token"""
    url = f'{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal'
    payload = {'app_id': FEISHU_APP_ID, 'app_secret': FEISHU_APP_SECRET}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if data.get('code') == 0:
            logger.info(f"获取tenant_access_token成功，有效期 {data.get('expire', 0)}s")
            return data['tenant_access_token']
        logger.error(f"获取token失败: {data.get('msg')}")
        return None
    except Exception as e:
        logger.error(f"获取token异常: {e}")
        return None


def get_wiki_spreadsheet_token(token, node_token):
    """通过wiki node_token获取底层spreadsheet的obj_token"""
    url = f'{FEISHU_API_BASE}/wiki/v2/spaces/get_node'
    headers = {'Authorization': f'Bearer {token}'}
    params = {'token': node_token}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        data = resp.json()
        if data.get('code') == 0:
            node = data.get('data', {}).get('node', {})
            obj_token = node.get('obj_token')
            obj_type = node.get('obj_type')
            logger.info(f"wiki节点解析成功: obj_type={obj_type}, obj_token={obj_token}")
            if obj_type != 'sheet':
                logger.error(f"wiki节点类型不是sheet，而是 {obj_type}")
                return None
            return obj_token
        logger.error(f"wiki get_node失败: code={data.get('code')}, msg={data.get('msg')}")
        return None
    except Exception as e:
        logger.error(f"wiki get_node异常: {e}")
        return None


def get_sheet_info(token, spreadsheet_token):
    """获取电子表格的工作表列表"""
    url = f'{FEISHU_API_BASE}/sheets/v3/spreadsheets/{spreadsheet_token}/sheets/query'
    headers = {'Authorization': f'Bearer {token}'}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        if data.get('code') == 0:
            sheets = data.get('data', {}).get('sheets', [])
            for s in sheets:
                gp = s.get('grid_properties', {})
                logger.info(f"  工作表: {s.get('title')} | ID: {s.get('sheet_id')} | "
                           f"rows={gp.get('row_count')} cols={gp.get('column_count')}")
            return sheets
        logger.error(f"获取工作表失败: code={data.get('code')}, msg={data.get('msg')}")
        return []
    except Exception as e:
        logger.error(f"获取工作表异常: {e}")
        return []


def read_spreadsheet(token, spreadsheet_token, sheet_id, row_count=None):
    """读取飞书电子表格数据

    飞书API默认只返回100行，需要显式指定范围来读取更多。
    """
    # 显式指定范围以突破默认100行限制
    max_rows = row_count or 2000
    range_str = f'{sheet_id}!A1:AZ{max_rows}'
    url = (f'{FEISHU_API_BASE}/sheets/v2/spreadsheets/{spreadsheet_token}'
           f'/values/{range_str}')
    headers = {'Authorization': f'Bearer {token}'}
    params = {
        'valueRenderOption': 'ToString',
        'dateTimeRenderOption': 'FormattedString',
    }
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        if data.get('code') == 0:
            values = data.get('data', {}).get('valueRange', {}).get('values', [])
            logger.info(f"读取到 {len(values)} 行数据（含表头）")
            return values
        logger.error(f"读取表格失败: code={data.get('code')}, msg={data.get('msg')}")
        return None
    except Exception as e:
        logger.error(f"读取表格异常: {e}")
        return None


def cell(row, col_idx):
    """安全取单元格值"""
    if col_idx < len(row):
        v = row[col_idx]
        if v is None:
            return ''
        return str(v).strip()
    return ''


def parse_date(value):
    """解析日期字段，支持多种格式"""
    if not value:
        return None
    value = str(value).strip()

    for fmt in ('%Y-%m-%d', '%Y/%m/%d', '%Y.%m.%d', '%m/%d/%Y',
                '%Y年%m月%d日', '%Y/%m/%d', '%Y-%m-%d'):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue

    # Excel序列号（飞书有时返回这个）
    try:
        serial = float(value)
        if 40000 < serial < 50000:
            base = datetime(1899, 12, 30)
            return (base + timedelta(days=int(serial))).date().isoformat()
    except (ValueError, TypeError):
        pass

    return None


def parse_amount(value):
    """解析金额字段，从字符串中提取数字"""
    if not value:
        return None
    value = str(value).strip().replace(',', '').replace('¥', '').replace('￥', '')
    try:
        return float(value)
    except (ValueError, TypeError):
        pass

    # 尝试从文本中提取数字（如 "2026/1/3支付宝收2920" → 2920）
    numbers = re.findall(r'(\d+(?:\.\d+)?)', value)
    if numbers:
        # 取最大的数字作为金额
        amounts = [float(n) for n in numbers if float(n) > 100]
        if amounts:
            return max(amounts)

    return None


def parse_deposit_from_note(note):
    """从订金备注中提取订金金额，如 "2026/1/3支付宝收2920" → 2920"""
    return parse_amount(note)


def parse_balance_from_note(note):
    """从尾款备注中提取尾款金额，如 "尾款金额6626" → 6626"""
    return parse_amount(note)


def determine_order_stage(amount, payment_status):
    """根据金额和收款状态判断订单阶段
    规则：
    - amount == 1000 → deposit（只付了定金）
    - amount > 1000 → won（成交）
    - 确认已收全款 → won
    - 确认已收订金 → deposit
    - 其他 → deposit（默认保守判断）
    """
    ps = str(payment_status or '').strip()

    if '全款' in ps:
        return 'won'
    if '订金' in ps and '全' not in ps:
        return 'deposit'

    if amount is not None:
        if amount == 1000:
            return 'deposit'
        if amount > 1000:
            return 'won'

    return 'deposit'


def map_payment_status(raw_status):
    """将飞书原始收款状态映射为orders表允许的值

    orders表CHECK约束允许: 待付定金, 已付定金, 已付全款
    """
    if not raw_status:
        return '待付定金'

    s = str(raw_status).strip()

    if '全款' in s:
        return '已付全款'
    if '订金' in s or '定金' in s:
        return '已付定金'

    return '待付定金'


def build_wechat_lookup(supabase):
    """从contacts表构建 alias/remark → wechat_id 的反查映射

    返回两个字典：
        exact_map: {alias或remark精确值: wechat_id} （唯一匹配）
        ambiguous: {alias或remark值: [wechat_id列表]} （多个匹配，需跳过）
    """
    logger.info("构建contacts反查映射表...")
    # 拉取所有contacts的wechat_id, wechat_alias, remark
    all_contacts = []
    offset = 0
    while True:
        r = (supabase.table('contacts')
             .select('wechat_id,wechat_alias,remark')
             .range(offset, offset + 999)
             .execute())
        if not r.data:
            break
        all_contacts.extend(r.data)
        if len(r.data) < 1000:
            break
        offset += 1000

    logger.info(f"  加载了 {len(all_contacts)} 条contacts记录")

    # 构建映射：key → set of wechat_ids
    key_to_wxids = {}
    for c in all_contacts:
        wxid = c.get('wechat_id', '')
        if not wxid:
            continue
        for field in ('wechat_alias', 'remark'):
            val = (c.get(field) or '').strip()
            if val:
                key_to_wxids.setdefault(val, set()).add(wxid)

    # 分离唯一匹配和歧义匹配
    exact_map = {}
    ambiguous = {}
    for key, wxids in key_to_wxids.items():
        if len(wxids) == 1:
            exact_map[key] = next(iter(wxids))
        else:
            ambiguous[key] = list(wxids)

    logger.info(f"  反查映射: {len(exact_map)}个唯一匹配, {len(ambiguous)}个歧义项")
    return exact_map, ambiguous


def resolve_wechat_id(raw_value, exact_map, ambiguous):
    """将飞书D列原始值解析为wxid

    逻辑：
    1. 如果已经是wxid_开头，直接返回
    2. 精确匹配exact_map（alias或remark）
    3. 如果精确匹配不到，尝试模糊匹配（remark包含该值）
    4. 匹配到唯一结果返回wxid，多个结果或无结果返回None

    返回: (resolved_wxid, match_type) 或 (None, reason)
    """
    if not raw_value:
        return None, 'empty'

    # 已经是wxid格式
    if raw_value.startswith('wxid_'):
        return raw_value, 'wxid'

    # 精确匹配alias或remark
    if raw_value in exact_map:
        return exact_map[raw_value], 'exact'

    # 模糊匹配：遍历exact_map找remark包含该值的
    fuzzy_matches = set()
    for key, wxid in exact_map.items():
        if raw_value in key:
            fuzzy_matches.add(wxid)

    if len(fuzzy_matches) == 1:
        return next(iter(fuzzy_matches)), 'fuzzy'
    if len(fuzzy_matches) > 1:
        return None, f'fuzzy_ambiguous({len(fuzzy_matches)})'

    # 检查歧义映射
    if raw_value in ambiguous:
        return None, f'ambiguous({len(ambiguous[raw_value])})'

    return None, 'no_match'


def parse_rows(rows, source_tag, wechat_lookup=None):
    """将表格行解析为订单记录

    Args:
        rows: 表格数据（含表头）
        source_tag: 来源标识，用于生成唯一的feishu_record_id
        wechat_lookup: (exact_map, ambiguous) 反查映射，None则不做反查
    """
    if not rows or len(rows) < 2:
        logger.warning("表格数据不足（无数据行）")
        return []

    header = rows[0]
    logger.info(f"表头: {[str(h)[:15] for h in header[:26] if h]}")

    exact_map, ambiguous = wechat_lookup or ({}, {})

    orders = []
    skipped = 0
    resolve_stats = {'wxid': 0, 'exact': 0, 'fuzzy': 0, 'failed': 0}

    for row_idx, row in enumerate(rows[1:], start=2):
        # 微信号必填
        raw_wechat = cell(row, COL_WECHAT_ID)
        if not raw_wechat:
            skipped += 1
            continue

        # T-026b: 反查逻辑 — 如果D列不是wxid格式，通过contacts表反查
        wechat_id, match_type = resolve_wechat_id(raw_wechat, exact_map, ambiguous)
        if wechat_id:
            if match_type != 'wxid':
                logger.info(f"  第{row_idx}行 反查成功: '{raw_wechat}' → {wechat_id} ({match_type})")
            resolve_stats[match_type if match_type in resolve_stats else 'exact'] += 1
        else:
            # 反查失败，仍使用原始值（保持向后兼容）
            wechat_id = raw_wechat
            resolve_stats['failed'] += 1
            logger.warning(f"  第{row_idx}行 反查失败: '{raw_wechat}' ({match_type})")

        # 解析日期（优先用A列下单期，备用T列下单时间）
        order_date = parse_date(cell(row, COL_ORDER_DATE))
        if not order_date:
            order_date = parse_date(cell(row, COL_ORDER_TIME))
        if not order_date:
            logger.warning(f"第{row_idx}行日期无效，跳过: '{cell(row, COL_ORDER_DATE)}'")
            skipped += 1
            continue

        # 解析金额
        amount = parse_amount(cell(row, COL_AMOUNT))

        # 产品：类型+品名
        product_type = cell(row, COL_PRODUCT_TYPE)
        product_name = cell(row, COL_PRODUCT_NAME)
        product = product_type
        if product_name and product_name != product_type:
            product = f"{product_type}-{product_name}" if product_type else product_name

        # 客服→sales_id
        sales_name = cell(row, COL_SALES_NAME)
        sales_id = SALES_NAME_TO_ID.get(sales_name)
        if not sales_id and sales_name:
            logger.debug(f"第{row_idx}行未知客服: '{sales_name}'")

        # 订金/尾款
        deposit = parse_deposit_from_note(cell(row, COL_DEPOSIT_NOTE))
        balance = parse_balance_from_note(cell(row, COL_BALANCE_NOTE))

        # 收款状态（飞书原始值→orders表允许的值）
        payment_status_raw = cell(row, COL_PAYMENT_STATUS)
        payment_status = map_payment_status(payment_status_raw)

        # 订单阶段（如果order_stage列已添加则写入）
        order_stage = determine_order_stage(amount, payment_status_raw)

        # 备注
        notes = cell(row, COL_NOTES) or None

        # T-026c: 新增字段
        customer_name = cell(row, COL_CUSTOMER_NAME) or None
        taobao_id = cell(row, COL_TAOBAO_ID) or None
        receiver_name = cell(row, COL_RECEIVER_NAME) or None
        phone = cell(row, COL_PHONE) or None
        address = cell(row, COL_ADDRESS) or None
        size = cell(row, COL_SIZE) or None
        sides = cell(row, COL_SIDES) or None
        fabric = cell(row, COL_FABRIC) or None
        requirement_detail = cell(row, COL_REQ_DETAIL) or None
        payment_channel = cell(row, COL_PAY_CHANNEL) or None
        manufacturer = cell(row, COL_MANUFACTURER) or None
        production_status = cell(row, COL_PROD_STATUS) or None
        shipping_date = parse_date(cell(row, COL_SHIPPING_DATE))
        logistics_company = cell(row, COL_LOGISTICS) or None

        order = {
            'wechat_id': wechat_id,
            'order_date': order_date,
            'amount': amount,
            'product': product or None,
            'sales_id': sales_id,
            'deposit': deposit or 0,
            'balance': balance or 0,
            'payment_status': payment_status,
            'delivery_status': '待生产',
            'feishu_record_id': f"{source_tag}_row{row_idx}",
            'notes': notes,
            'customer_name': customer_name,
            'taobao_id': taobao_id,
            'receiver_name': receiver_name,
            'phone': phone,
            'address': address,
            'size': size,
            'sides': sides,
            'fabric': fabric,
            'requirement_detail': requirement_detail,
            'payment_channel': payment_channel,
            'manufacturer': manufacturer,
            'production_status': production_status,
            'shipping_date': shipping_date,
            'logistics_company': logistics_company,
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }

        # order_stage列可能尚未添加，先标记在_extra里
        order['_order_stage'] = order_stage

        orders.append(order)

    logger.info(f"解析完成: {len(orders)}条有效订单, {skipped}条跳过")
    logger.info(f"  wechat_id解析统计: {resolve_stats}")
    return orders


def check_order_stage_column(supabase):
    """检查order_stage列是否存在"""
    try:
        supabase.table('orders').select('order_stage').limit(1).execute()
        return True
    except Exception:
        return False


def get_existing_record_ids(supabase):
    """获取已有的feishu_record_id集合，用于去重"""
    existing = set()
    try:
        # 分页获取所有非空的feishu_record_id
        offset = 0
        while True:
            r = (supabase.table('orders')
                 .select('feishu_record_id')
                 .not_.is_('feishu_record_id', 'null')
                 .range(offset, offset + 999)
                 .execute())
            if not r.data:
                break
            for row in r.data:
                existing.add(row['feishu_record_id'])
            if len(r.data) < 1000:
                break
            offset += 1000
    except Exception as e:
        logger.warning(f"获取已有record_id失败: {e}")
    logger.info(f"已有 {len(existing)} 条带feishu_record_id的订单")
    return existing


def sync_to_supabase(supabase, orders):
    """批量写入Supabase orders表（upsert by feishu_record_id）

    T-026c: 改为upsert模式，已有记录也会更新新字段
    """
    if not orders:
        logger.info("无订单需要同步")
        return 0, 0

    # 检查order_stage列是否存在
    has_stage = check_order_stage_column(supabase)
    if has_stage:
        logger.info("order_stage列存在，将写入订单阶段")

    # 清理数据：移除_extra字段，按需添加order_stage
    for order in orders:
        stage = order.pop('_order_stage', None)
        if has_stage and stage:
            order['order_stage'] = stage

    # 区分新增和更新
    existing_ids = get_existing_record_ids(supabase)
    new_orders = [o for o in orders if o['feishu_record_id'] not in existing_ids]
    update_orders = [o for o in orders if o['feishu_record_id'] in existing_ids]

    logger.info(f"新增 {len(new_orders)} 条, 更新 {len(update_orders)} 条")

    inserted = 0
    updated = 0
    batch_size = 50

    # 新增
    for i in range(0, len(new_orders), batch_size):
        batch = new_orders[i:i + batch_size]
        try:
            supabase.table('orders').insert(batch).execute()
            inserted += len(batch)
            logger.info(f"新增 {inserted}/{len(new_orders)} 条")
        except Exception as e:
            logger.error(f"批量新增失败: {e}")
            for row in batch:
                try:
                    supabase.table('orders').insert(row).execute()
                    inserted += 1
                except Exception as e2:
                    logger.warning(f"单条新增失败 (wechat={row.get('wechat_id')}, "
                                 f"date={row.get('order_date')}): {e2}")

    # 更新已有记录（用feishu_record_id匹配，upsert）
    for i in range(0, len(update_orders), batch_size):
        batch = update_orders[i:i + batch_size]
        try:
            supabase.table('orders').upsert(
                batch, on_conflict='feishu_record_id'
            ).execute()
            updated += len(batch)
            logger.info(f"更新 {updated}/{len(update_orders)} 条")
        except Exception as e:
            logger.error(f"批量更新失败: {e}")
            for row in batch:
                try:
                    supabase.table('orders').upsert(
                        row, on_conflict='feishu_record_id'
                    ).execute()
                    updated += 1
                except Exception as e2:
                    logger.warning(f"单条更新失败 (frid={row.get('feishu_record_id')}): {e2}")

    logger.info(f"同步完成: 新增 {inserted}, 更新 {updated}")
    return inserted, updated


def main():
    parser = argparse.ArgumentParser(description='T-016: 飞书wiki订单同步')
    parser.add_argument('--dry-run', action='store_true',
                       help='只读取和解析，不写入数据库')
    parser.add_argument('--wiki-only', action='store_true',
                       help='只同步wiki表格（2026），不同步其他sheets')
    parser.add_argument('--all', action='store_true',
                       help='同步所有表格（wiki + 其他sheets）')
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("T-016: 飞书wiki订单同步开始")
    logger.info("=" * 60)

    # 检查环境变量
    missing = []
    if not FEISHU_APP_ID:
        missing.append('FEISHU_APP_ID')
    if not FEISHU_APP_SECRET:
        missing.append('FEISHU_APP_SECRET')
    if not SUPABASE_KEY:
        missing.append('SUPABASE_SERVICE_ROLE_KEY')
    if missing:
        logger.error(f"缺少环境变量: {', '.join(missing)}")
        sys.exit(1)

    # 1. 获取飞书访问令牌
    token = get_tenant_access_token()
    if not token:
        logger.error("无法获取飞书访问令牌，退出")
        sys.exit(1)

    # 1b. T-026b: 构建contacts反查映射（用于将飞书alias→wxid）
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    wechat_lookup = build_wechat_lookup(supabase)

    all_orders = []

    # 2. 读取wiki表格（2026订单）
    logger.info("\n--- 读取wiki表格 (2026订单) ---")
    wiki_spreadsheet_token = get_wiki_spreadsheet_token(token, WIKI_NODE_TOKEN)
    if wiki_spreadsheet_token:
        sheets = get_sheet_info(token, wiki_spreadsheet_token)
        if sheets:
            # 只读第一个有数据的sheet
            sheet_id = sheets[0].get('sheet_id')
            row_count = sheets[0].get('grid_properties', {}).get('row_count', 2000)
            rows = read_spreadsheet(token, wiki_spreadsheet_token, sheet_id, row_count)
            if rows:
                orders = parse_rows(rows, 'wiki2026', wechat_lookup)
                all_orders.extend(orders)
    else:
        logger.error("无法解析wiki节点，跳过wiki表格")

    # 3. 可选：也同步其他普通sheets表格
    if args.all and not args.wiki_only:
        for st in EXTRA_SPREADSHEET_TOKENS:
            st = st.strip()
            if not st:
                continue
            logger.info(f"\n--- 读取普通表格 {st[:10]}... ---")
            sheets = get_sheet_info(token, st)
            if sheets:
                sheet_id = sheets[0].get('sheet_id')
                row_count = sheets[0].get('grid_properties', {}).get('row_count', 2000)
                rows = read_spreadsheet(token, st, sheet_id, row_count)
                if rows:
                    tag = f"sheet_{st[:8]}"
                    orders = parse_rows(rows, tag, wechat_lookup)
                    all_orders.extend(orders)

    logger.info(f"\n总计: {len(all_orders)} 条订单待同步")

    # 4. 预览或写入
    if args.dry_run:
        logger.info("=== DRY RUN: 解析结果预览 ===")
        stage_counts = {}
        wxid_count = 0
        alias_count = 0
        for order in all_orders:
            stage = order.get('_order_stage', 'unknown')
            stage_counts[stage] = stage_counts.get(stage, 0) + 1
            if order['wechat_id'].startswith('wxid_'):
                wxid_count += 1
            else:
                alias_count += 1

        for i, order in enumerate(all_orders[:15]):
            stage = order.get('_order_stage', '?')
            wxid_flag = '✓' if order['wechat_id'].startswith('wxid_') else '✗'
            print(f"  [{i+1}] {wxid_flag} {order['wechat_id'][:22]:22s} | "
                  f"{order['order_date']} | "
                  f"¥{order['amount'] or '?':>8} | "
                  f"{stage:7s} | "
                  f"{(order['product'] or '-')[:15]:15s} | "
                  f"{order.get('payment_status', '-')[:10]}")
        if len(all_orders) > 15:
            print(f"  ... 共 {len(all_orders)} 条")

        print(f"\n  阶段统计: {stage_counts}")
        print(f"  wxid格式: {wxid_count}, 别名(未解析): {alias_count}")
        return

    # 5. 写入Supabase（supabase client已在步骤1b创建）
    inserted, updated = sync_to_supabase(supabase, all_orders)

    logger.info("=" * 60)
    logger.info(f"T-026c 同步完成: 新增 {inserted} 条, 更新 {updated} 条")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
