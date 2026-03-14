#!/usr/bin/env python3
"""
T-033 B组四步诊断量产 — Batch API + Prompt Cache 版本
4轮批量提交（Step1→Step2→Step3→Step4），每轮等待完成后再提交下一轮。
Batch API 半价 + 共享System Prompt缓存 = 大幅降本。
支持断点续跑：中间状态保存到 T033_state.json。
输出：按销售分3个HTML + 1个JSON原始数据。
"""

import os, sys, json, time, re, logging, traceback
from datetime import datetime, date, timezone, timedelta

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

SUPABASE_URL = os.getenv('SUPABASE_URL', 'https://dieeejjzbhkpgxdhwlxf.supabase.co')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')

from supabase import create_client
import anthropic, httpx

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
proxy = os.getenv('ANTHROPIC_PROXY', 'http://127.0.0.1:7897')
http_client = httpx.Client(proxy=proxy, timeout=120.0)
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, http_client=http_client)

HAIKU = 'claude-haiku-4-5-20251001'

SALES_IDS = [
    'wxid_am3kdib9tt3722',   # 可欣
    'wxid_p03xoj66oss112',   # 小杰
    'wxid_cbk7hkyyp11t12',   # 霄剑
]
SALES_NAMES = {
    'wxid_am3kdib9tt3722': '可欣',
    'wxid_p03xoj66oss112': '小杰',
    'wxid_cbk7hkyyp11t12': '霄剑',
}
ACTION_CN = {
    'rush': '🔴立刻跟', 'follow': '🟠持续跟', 'revive': '🟡值得捞',
    'nurture': '⚪低优养着', 'drop': '⛔别浪费',
}

INTERNAL_IDS = {
    'wxid_am3kdib9tt3722', 'wxid_p03xoj66oss112', 'wxid_cbk7hkyyp11t12',
    'wxid_n98h2ys469bm12', 'wxid_aufah51bw9ok22', 'wxid_blcq5kt11il212',
    'wxid_p3cqnq00wpz322',
}
SYSTEM_IDS = {'filehelper', 'weixin'}
SUPPLIER_KEYWORDS = [
    '皮革', '面料', '客服', '跟单', '海运', '快递', '物流', '制造商',
    '皮业', '五金', '家居-', '家具-', '@openim', '凯特罗格', 'WOWTEX',
    '览秀', '4PX', '巴斯皮革', 'MOTOO', '华达皮业', '米格朵', '唯纳罗木',
    '威赫-小家', '允家家居', '时增皮革', '思千家具', '博简居',
]

TODAY_STR = date.today().strftime('%Y年%m月%d日')
DIAG_DIR = os.path.join(os.path.expanduser('~'), 'Desktop', '诊断结果')
STATE_FILE = os.path.join(DIAG_DIR, 'T033_state.json')


# ============ Shared System Prompts (cached across batch requests) ============

SYSTEM_STEP1 = """你是莫妮卡摩卡高定家具品牌的数据分析师。请从聊天记录中提取恰好6项事实。

请严格按JSON输出：
{
  "last_customer_msg": "客户最后一条主动消息的原文（非群发）",
  "last_customer_msg_time": "该消息的时间（mm-dd HH:MM格式）",
  "renovation_stage": "装修阶段（引用原文证据，如'客户说还没交房'。无证据写'未提及'）",
  "core_needs": "核心需求/顾虑（如'想买岩石沙发3米，担心面料掉色'。无明确需求写'未明确'）",
  "price_discussion": "价格讨论情况（如'报价21850，客户说贵了'。未讨论价格写'未报价'）",
  "progress_actions": "推进动作（报价/寄样/到访/拉群等，列举已发生的。无则写'无'）",
  "emotion_trend": "客户情绪走向（热→冷/冷→热/持平/无法判断，引用证据）"
}
只输出JSON，不要其他内容。"""

SYSTEM_STEP2 = f"""你是莫妮卡摩卡的销售诊断AI。基于事实清单判断客户应该用哪个动作跟进。

⚠️ 今天的日期是 {TODAY_STR}。计算沉默天数时必须用今天的日期减去客户最后消息日期。

## 硬规则（必须遵守）
- 客户说买了/定了别家 → drop
- 客户最后消息是主动询问+销售未回复+沉默<90天 → rush
- 客户最后消息是主动询问+销售未回复+沉默≥90天 → revive
- 排除群发后沉默>90天无客户主动消息 → drop
- 加微>6个月+客户0消息 → drop
- 客户删好友 → drop
- 非品类需求（沙发床/餐桌椅等） → revive
- 客户有明确偏好+已询价+未成交 → follow
- 报价后沉默>48小时（积极→follow，冷淡→revive）
- 沉默14-90天+深度互动 → revive
- 沉默14-90天+浅度互动 → nurture

## 范例
范例1：客户3月1日问"定金多少"，销售至今未回复 → {{"action":"rush","reason":"销售漏回复客户定金问题","do_this":"立即回复定金流程，发岩石沙发报价单","risk":null}}
范例2：客户沉默5个月，期间销售群发3次无回应 → {{"action":"drop","reason":"沉默超90天，大概率已购买","do_this":"不主动跟进","risk":null}}
范例3：客户讨论过面料和尺寸，2天前销售报价后未回 → {{"action":"follow","reason":"报价后沉默，客户之前态度积极","do_this":"发岩石沙发棉麻实拍对比图，问客户倾向","risk":"报价后沉默"}}

请输出JSON：
{{
  "action": "rush/follow/revive/nurture/drop",
  "reason": "20字内",
  "do_this": "50字内",
  "risk": "没有则null",
  "self_critique": ["可能错的原因1", "可能错的原因2", "可能错的原因3"]
}}
只输出JSON。"""

SYSTEM_STEP3 = """你是莫妮卡摩卡的诊断质检员。检查诊断是否有遗漏或矛盾。

请检查：
1. 事实清单是否遗漏了聊天记录中的重要信息？
2. 诊断动作是否与事实矛盾？
3. AI自己列的可能错误，是否确实存在？

如果发现问题需要修正，输出修正后的JSON；如果没问题，原样返回：
{
  "validated": true或false,
  "action": "rush/follow/revive/nurture/drop",
  "reason": "20字内",
  "do_this": "50字内",
  "risk": null或"15字内",
  "validation_note": "检查结论（1-2句话）"
}
只输出JSON。"""

SYSTEM_STEP4 = """你是Monica，莫妮卡摩卡的老板。你最讨厌AI把所有客户都判rush浪费销售精力，也讨厌把有价值客户判drop错过机会。

强制二选一——这个诊断你是否同意？
- 同意：原样返回JSON
- 不同意：给出你的修正

输出JSON：
{
  "agree": true或false,
  "action": "rush/follow/revive/nurture/drop",
  "reason": "20字内",
  "do_this": "50字内",
  "risk": "没有则null",
  "monica_note": "Monica的判断理由（1句话）"
}
只输出JSON。"""


# ============ DB Helpers ============
def supabase_retry(fn, retries=3):
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            if attempt < retries - 1:
                logger.warning(f"  Supabase重试 {attempt+1}: {e}")
                time.sleep(2)
            else:
                raise


def fetch_active_customers():
    """查询3位销售近30天有私聊消息的客户（排除成交+群聊+内部+供应商）"""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    customers = []

    # 一次性查成交订单
    won_ids = set()
    resp = supabase_retry(lambda: supabase.table('orders').select('wechat_id').eq('order_stage', 'won').execute())
    for row in (resp.data or []):
        if row.get('wechat_id'):
            won_ids.add(row['wechat_id'])
    resp = supabase_retry(lambda: supabase.table('orders').select('wechat_id, amount').eq('order_stage', 'deposit').execute())
    for row in (resp.data or []):
        if row.get('wechat_id') and row.get('amount') and float(row['amount']) > 1000:
            won_ids.add(row['wechat_id'])

    for sales_id in SALES_IDS:
        sales_name = SALES_NAMES[sales_id]
        page_size = 1000
        all_wechat_ids = set()
        offset = 0
        while True:
            resp = supabase_retry(lambda o=offset: supabase.table('chat_messages').select(
                'wechat_id'
            ).eq('sales_wechat_id', sales_id
            ).eq('is_system_msg', False
            ).gte('sent_at', cutoff
            ).not_('room_id', 'like', '%@chatroom%'
            ).range(o, o + page_size - 1).execute())
            batch = resp.data or []
            for row in batch:
                all_wechat_ids.add(row['wechat_id'])
            if len(batch) < page_size:
                break
            offset += page_size

        active_ids = all_wechat_ids - won_ids - INTERNAL_IDS - SYSTEM_IDS

        supplier_ids = set()
        no_contact_ids = set()
        for wid in list(active_ids):
            if '@openim' in wid:
                supplier_ids.add(wid)
                continue
            contact = supabase_retry(lambda w=wid: supabase.table('contacts').select(
                'nickname, remark'
            ).eq('wechat_id', w).eq('sales_wechat_id', sales_id).limit(1).execute())
            if not contact.data:
                no_contact_ids.add(wid)
                continue
            combined = (contact.data[0].get('nickname') or '') + (contact.data[0].get('remark') or '')
            for kw in SUPPLIER_KEYWORDS:
                if kw in combined:
                    supplier_ids.add(wid)
                    break

        active_ids = active_ids - supplier_ids - no_contact_ids
        n_won = len(won_ids & all_wechat_ids)
        n_int = len((INTERNAL_IDS | SYSTEM_IDS) & all_wechat_ids)
        logger.info(f"  {sales_name}: {len(all_wechat_ids)}人 → 排除成交{n_won}+内部{n_int}+供应商{len(supplier_ids)}+无记录{len(no_contact_ids)} → {len(active_ids)}人")
        for wid in active_ids:
            customers.append((wid, sales_id))

    logger.info(f"总计待诊断: {len(customers)}人")
    return customers


def fetch_chat_history(contact_wechat_id, sales_wechat_id):
    PAGE = 1000
    all_msgs = []
    offset = 0
    while True:
        resp = supabase_retry(lambda o=offset: supabase.table('chat_messages').select(
            'content, sender_type, sent_at, msg_type, is_system_msg'
        ).eq('wechat_id', contact_wechat_id).eq(
            'sales_wechat_id', sales_wechat_id
        ).eq('is_system_msg', False
        ).not_('room_id', 'like', '%@chatroom%'
        ).order('sent_at').range(o, o + PAGE - 1).execute())
        batch = resp.data or []
        all_msgs.extend(batch)
        if len(batch) < PAGE:
            break
        offset += PAGE
    return all_msgs


def build_chat_text(msgs, limit=None):
    recent = msgs[-limit:] if limit and len(msgs) > limit else msgs
    lines = []
    for m in recent:
        sender = '客户' if m.get('sender_type') != 'sales' else '销售'
        content = m.get('content', '') or ''
        msg_type = str(m.get('msg_type', '1'))
        if msg_type == '3':
            display = content.strip() if content.strip() and not content.strip().isdigit() else '[语音消息]'
        elif msg_type in ('2', '4', '5', '6', '7', '8', '42', '43', '47', '48', '49', '51'):
            type_labels = {'2': '[图片]', '4': '[视频]', '5': '[链接]', '6': '[文件]',
                           '7': '[动图]', '8': '[动图]', '42': '[名片]', '43': '[视频]',
                           '47': '[动图]', '48': '[位置]', '49': '[文件/链接]', '51': '[视频通话]'}
            display = type_labels.get(msg_type, f'[类型{msg_type}]')
        else:
            display = content.strip() if content.strip() else '[空消息]'
        sent_at = m.get('sent_at', '')
        time_str = ''
        if sent_at:
            try:
                dt = datetime.fromisoformat(sent_at.replace('Z', '+00:00'))
                time_str = dt.strftime('%m-%d %H:%M')
            except:
                time_str = sent_at[:16]
        lines.append(f"[{sender} {time_str}] {display}")
    return '\n'.join(lines), len(recent)


def parse_json_response(text, label=''):
    text = text.strip()
    if text.startswith('```'):
        lines = text.split('\n')
        lines = [l for l in lines if not l.strip().startswith('```')]
        text = '\n'.join(lines).strip()
    try:
        return json.loads(text)
    except:
        m = re.search(r'\{[\s\S]*\}', text)
        if m:
            try:
                return json.loads(m.group())
            except:
                cleaned = re.sub(r',\s*}', '}', m.group())
                cleaned = re.sub(r',\s*]', ']', cleaned)
                try:
                    return json.loads(cleaned)
                except:
                    pass
    if label:
        logger.warning(f"  {label} JSON解析失败")
    return {'_raw': text[:500], '_parse_error': True}


# ============ State Management ============
def save_state(state):
    os.makedirs(DIAG_DIR, exist_ok=True)
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    logger.info(f"状态已保存: {STATE_FILE}")


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None


# ============ Batch API ============
def submit_batch(step_name, requests):
    """提交Batch请求，返回batch_id"""
    logger.info(f"提交 {step_name}: {len(requests)} 个请求")
    batch = claude.messages.batches.create(requests=requests)
    logger.info(f"  Batch ID: {batch.id}, 状态: {batch.processing_status}")
    return batch.id


def wait_for_batch(batch_id, step_name, poll_interval=30):
    """轮询等待Batch完成，返回结果字典 {custom_id: response_text}"""
    while True:
        batch = claude.messages.batches.retrieve(batch_id)
        counts = batch.request_counts
        total = counts.processing + counts.succeeded + counts.errored + counts.canceled + counts.expired
        logger.info(f"  {step_name} [{batch.processing_status}] "
                     f"成功{counts.succeeded}/{total} 失败{counts.errored} 处理中{counts.processing}")
        if batch.processing_status == 'ended':
            break
        time.sleep(poll_interval)

    results = {}
    for result in claude.messages.batches.results(batch_id):
        cid = result.custom_id
        if result.result.type == 'succeeded':
            msg = result.result.message
            text = ''.join(b.text for b in msg.content if hasattr(b, 'text'))
            results[cid] = text
        else:
            results[cid] = json.dumps({'_error': result.result.type})
    logger.info(f"  {step_name} 完成: {len(results)} 个结果")
    return results


# ============ Build Batch Requests ============
def build_step1_requests(customers_data):
    requests = []
    for cid, cdata in customers_data.items():
        user_msg = f"""客户：{cdata['nickname']}，备注：{cdata['remark']}，消息{cdata['msg_total']}条（客户{cdata['msg_customer']}/销售{cdata['msg_sales']}），订单：{cdata['order_stage']}

聊天记录（{cdata['msg_count_recent']}条）：
{cdata['chat_text']}"""
        requests.append({
            'custom_id': cid,
            'params': {
                'model': HAIKU,
                'max_tokens': 512,
                'system': [{'type': 'text', 'text': SYSTEM_STEP1,
                            'cache_control': {'type': 'ephemeral'}}],
                'messages': [{'role': 'user', 'content': user_msg}],
            }
        })
    return requests


def build_step2_requests(customers_data, step1_results):
    requests = []
    for cid, cdata in customers_data.items():
        raw1 = step1_results.get(cid, '{}')
        facts = parse_json_response(raw1)
        facts_text = json.dumps(facts, ensure_ascii=False, indent=2) if not facts.get('_parse_error') else raw1

        user_msg = f"""## 事实清单
{facts_text}

## 客户基本信息
昵称：{cdata['nickname']}，备注：{cdata['remark']}，消息{cdata['msg_total']}条（客户{cdata['msg_customer']}/销售{cdata['msg_sales']}），订单：{cdata['order_stage']}"""
        requests.append({
            'custom_id': cid,
            'params': {
                'model': HAIKU,
                'max_tokens': 512,
                'system': [{'type': 'text', 'text': SYSTEM_STEP2,
                            'cache_control': {'type': 'ephemeral'}}],
                'messages': [{'role': 'user', 'content': user_msg}],
            }
        })
    return requests


def build_step3_requests(customers_data, step1_results, step2_results):
    requests = []
    for cid, cdata in customers_data.items():
        raw1 = step1_results.get(cid, '{}')
        facts = parse_json_response(raw1)
        facts_text = json.dumps(facts, ensure_ascii=False, indent=2) if not facts.get('_parse_error') else raw1
        raw2 = step2_results.get(cid, '{}')
        diag = parse_json_response(raw2)
        action = diag.get('action', '?')
        critique = diag.get('self_critique', [])

        user_msg = f"""以下是对客户"{cdata['nickname']}"的诊断结果和事实清单。

诊断结果：
- 动作：{ACTION_CN.get(action, action)}（{action}）
- 原因：{diag.get('reason', '')}
- 建议：{diag.get('do_this', '')}
- 风险：{diag.get('risk') or '无'}
- AI自己列的可能错误：{json.dumps(critique, ensure_ascii=False)}

事实清单：
{facts_text}

原始聊天记录（{cdata['msg_count_recent']}条）：
{cdata['chat_text']}"""
        requests.append({
            'custom_id': cid,
            'params': {
                'model': HAIKU,
                'max_tokens': 512,
                'system': [{'type': 'text', 'text': SYSTEM_STEP3,
                            'cache_control': {'type': 'ephemeral'}}],
                'messages': [{'role': 'user', 'content': user_msg}],
            }
        })
    return requests


def build_step4_requests(customers_data, step3_results):
    requests = []
    for cid, cdata in customers_data.items():
        raw3 = step3_results.get(cid, '{}')
        xval = parse_json_response(raw3)
        xval_action = xval.get('action', '?')

        user_msg = f"""以下是AI对客户"{cdata['nickname']}"的最终诊断：
- 动作：{ACTION_CN.get(xval_action, xval_action)}
- 原因：{xval.get('reason', '')}
- 建议：{xval.get('do_this', '')}
- 风险：{xval.get('risk') or '无'}

客户基本信息：备注{cdata['remark']}，消息{cdata['msg_total']}条（客户{cdata['msg_customer']}/销售{cdata['msg_sales']}），订单{cdata['order_stage']}

聊天记录（{cdata['msg_count_recent']}条）：
{cdata['chat_text']}"""
        requests.append({
            'custom_id': cid,
            'params': {
                'model': HAIKU,
                'max_tokens': 512,
                'system': [{'type': 'text', 'text': SYSTEM_STEP4,
                            'cache_control': {'type': 'ephemeral'}}],
                'messages': [{'role': 'user', 'content': user_msg}],
            }
        })
    return requests


# ============ Main ============
def main():
    logger.info("=" * 60)
    logger.info("T-033 B组四步诊断量产 (Batch API + Cache)")
    logger.info("=" * 60)
    os.makedirs(DIAG_DIR, exist_ok=True)

    state = load_state()
    if state and state.get('completed_step', 0) < 4:
        logger.info(f"发现断点状态，已完成到Step{state['completed_step']}，继续执行")
    else:
        state = {'completed_step': 0}

    # ===== Phase 0: 数据准备 =====
    if state['completed_step'] < 1:
        if 'customers_data' not in state:
            logger.info("Phase 0: 查询活跃客户并拉取聊天记录...")
            customer_list = fetch_active_customers()
            if not customer_list:
                logger.error("未查询到活跃客户")
                return

            customers_data = {}
            skipped = 0
            for i, (contact_id, sales_id) in enumerate(customer_list):
                contact = supabase_retry(lambda: supabase.table('contacts').select(
                    'nickname, remark, wechat_alias, add_time'
                ).eq('wechat_id', contact_id).eq('sales_wechat_id', sales_id).limit(1).execute())
                if not contact.data:
                    skipped += 1
                    continue
                c = contact.data[0]
                msgs = fetch_chat_history(contact_id, sales_id)
                if not msgs:
                    skipped += 1
                    continue

                chat_text, msg_count_recent = build_chat_text(msgs)
                customer_count = sum(1 for m in msgs if m.get('sender_type') != 'sales')
                sales_count_val = len(msgs) - customer_count

                # 查订单
                wechat_alias = c.get('wechat_alias', '') or ''
                order = supabase_retry(lambda: supabase.table('orders').select('order_stage').eq(
                    'wechat_id', contact_id).limit(1).execute())
                if not order.data and wechat_alias and wechat_alias != contact_id:
                    order = supabase_retry(lambda: supabase.table('orders').select('order_stage').eq(
                        'wechat_id', wechat_alias).limit(1).execute())
                order_stage = order.data[0]['order_stage'] if order.data else '无'

                cid = f"{contact_id}__{sales_id}"
                customers_data[cid] = {
                    'contact_id': contact_id, 'sales_id': sales_id,
                    'nickname': c.get('nickname', '未知'),
                    'remark': c.get('remark', '') or '',
                    'wechat_alias': wechat_alias,
                    'add_time': c.get('add_time', '') or '',
                    'sales': SALES_NAMES.get(sales_id, sales_id),
                    'msg_total': len(msgs), 'msg_customer': customer_count,
                    'msg_sales': sales_count_val, 'order_stage': order_stage,
                    'chat_text': chat_text, 'msg_count_recent': msg_count_recent,
                }
                if (i + 1) % 20 == 0:
                    logger.info(f"  数据准备: {i+1}/{len(customer_list)}")

            state['customers_data'] = customers_data
            state['skipped'] = skipped
            save_state(state)
            logger.info(f"数据准备完成: {len(customers_data)}人（跳过{skipped}）")

    customers_data = state['customers_data']

    # ===== Step 1: 事实提取 =====
    if state['completed_step'] < 1:
        logger.info(f"\nStep 1: 事实提取 ({len(customers_data)}人)")
        reqs = build_step1_requests(customers_data)
        batch_id = submit_batch('Step1-事实提取', reqs)
        state['batch_id_step1'] = batch_id
        save_state(state)
        results1 = wait_for_batch(batch_id, 'Step1-事实提取')
        state['step1_results'] = results1
        state['completed_step'] = 1
        save_state(state)

    # ===== Step 2: 诊断+自我批评 =====
    if state['completed_step'] < 2:
        logger.info(f"\nStep 2: 诊断+自我批评 ({len(customers_data)}人)")
        reqs = build_step2_requests(customers_data, state['step1_results'])
        batch_id = submit_batch('Step2-诊断', reqs)
        state['batch_id_step2'] = batch_id
        save_state(state)
        results2 = wait_for_batch(batch_id, 'Step2-诊断')
        state['step2_results'] = results2
        state['completed_step'] = 2
        save_state(state)

    # ===== Step 3: 交叉验证 =====
    if state['completed_step'] < 3:
        logger.info(f"\nStep 3: 交叉验证 ({len(customers_data)}人)")
        reqs = build_step3_requests(customers_data, state['step1_results'], state['step2_results'])
        batch_id = submit_batch('Step3-交叉验证', reqs)
        state['batch_id_step3'] = batch_id
        save_state(state)
        results3 = wait_for_batch(batch_id, 'Step3-交叉验证')
        state['step3_results'] = results3
        state['completed_step'] = 3
        save_state(state)

    # ===== Step 4: Monica对抗审核 =====
    if state['completed_step'] < 4:
        logger.info(f"\nStep 4: Monica对抗审核 ({len(customers_data)}人)")
        reqs = build_step4_requests(customers_data, state['step3_results'])
        batch_id = submit_batch('Step4-Monica审核', reqs)
        state['batch_id_step4'] = batch_id
        save_state(state)
        results4 = wait_for_batch(batch_id, 'Step4-Monica审核')
        state['step4_results'] = results4
        state['completed_step'] = 4
        save_state(state)

    # ===== 生成报告 =====
    logger.info("\n生成报告...")
    generate_reports(state)
    logger.info("全部完成!")


# ============ Report Generation ============
def generate_reports(state):
    import html as html_mod

    def esc(s):
        return html_mod.escape(str(s)) if s else ''

    customers_data = state['customers_data']
    s1 = state.get('step1_results', {})
    s2 = state.get('step2_results', {})
    s3 = state.get('step3_results', {})
    s4 = state.get('step4_results', {})

    # 组装每个客户的完整结果
    all_results = []
    for cid, cdata in customers_data.items():
        facts = parse_json_response(s1.get(cid, '{}'))
        diag = parse_json_response(s2.get(cid, '{}'))
        xval = parse_json_response(s3.get(cid, '{}'))
        monica = parse_json_response(s4.get(cid, '{}'))
        final_action = monica.get('action', xval.get('action', diag.get('action', '?')))
        all_results.append({
            **cdata,
            'facts': facts, 'diag': diag, 'xval': xval, 'monica': monica,
            'final_action': final_action,
        })

    # 按销售分组
    by_sales = {}
    for r in all_results:
        s = r['sales']
        by_sales.setdefault(s, []).append(r)

    # 全局统计
    action_dist = {}
    for r in all_results:
        a = r['final_action']
        action_dist[a] = action_dist.get(a, 0) + 1

    # 每个销售生成一个HTML
    for sales_name, sales_results in by_sales.items():
        _generate_sales_html(sales_name, sales_results, action_dist, all_results, esc)

    # JSON原始数据（不含chat_text节省空间）
    json_data = []
    for r in all_results:
        jr = {k: v for k, v in r.items() if k != 'chat_text'}
        jr['chat_msg_count'] = r.get('msg_count_recent', 0)
        json_data.append(jr)
    json_path = os.path.join(DIAG_DIR, f'T033-全部-{len(all_results)}人-{datetime.now().strftime("%m%d")}.json')
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    logger.info(f"JSON: {json_path}")


def _generate_sales_html(sales_name, results, global_dist, all_results, esc):
    n = len(results)
    # 该销售的action分布
    local_dist = {}
    for r in results:
        a = r['final_action']
        local_dist[a] = local_dist.get(a, 0) + 1
    dist_html = ' / '.join(f'{ACTION_CN.get(a,a)}: {local_dist.get(a,0)}'
                           for a in ['rush','follow','revive','nurture','drop'] if local_dist.get(a,0))

    monica_corrections = sum(1 for r in results if not r['monica'].get('agree', True))
    xval_corrections = sum(1 for r in results if not r['xval'].get('validated', True))

    # 总表
    summary_rows = ''
    for idx, r in enumerate(results):
        diag_action = r['diag'].get('action', '?')
        xval_action = r['xval'].get('action', diag_action)
        final = r['final_action']
        chg_xval = '→' + ACTION_CN.get(xval_action, xval_action) if xval_action != diag_action else '✅'
        chg_monica = '→' + ACTION_CN.get(final, final) if not r['monica'].get('agree', True) else '✅'

        summary_rows += f'''<tr>
            <td>{idx+1}</td>
            <td><a href="#c{idx}">{esc(r["nickname"])}</a></td>
            <td>{esc(r.get("wechat_alias",""))}</td>
            <td>{r["msg_total"]}</td>
            <td>{ACTION_CN.get(diag_action, diag_action)}</td>
            <td>{chg_xval}</td>
            <td>{chg_monica}</td>
            <td><b>{ACTION_CN.get(final, final)}</b></td>
            <td>{esc(r['monica'].get('reason',''))}</td>
            <td>{esc(r['monica'].get('do_this',''))}</td>
        </tr>\n'''

    # 详情卡片（聊天记录折叠）
    cards = ''
    for idx, r in enumerate(results):
        facts = r['facts']
        diag = r['diag']
        xval = r['xval']
        monica = r['monica']
        final = r['final_action']
        chat_lines = esc(r.get('chat_text', '')).replace('\n', '<br>')

        cards += f'''
        <div class="card" id="c{idx}">
            <div class="card-hdr">
                <span class="cn">#{idx+1}</span>
                <span class="nm">{esc(r['nickname'])}</span>
                <span class="wx">{esc(r.get('wechat_alias',''))}</span>
                <span class="act">{ACTION_CN.get(final, final)}</span>
                <span class="mt">备注:{esc(r.get('remark') or '无')} | {r['msg_total']}条(客{r['msg_customer']}/销{r['msg_sales']}) | 订单:{esc(r['order_stage'])}</span>
            </div>
            <div class="card-body">
                <div class="result-section">
                    <div class="final-box">
                        <b>最终判断：{ACTION_CN.get(final, final)}</b><br>
                        依据：{esc(monica.get('reason',''))}<br>
                        建议：{esc(monica.get('do_this',''))}<br>
                        风险：{esc(monica.get('risk') or '无')}
                        <p style="color:#CE93D8;font-size:11px;margin-top:4px">{esc(monica.get('monica_note',''))}</p>
                    </div>
                    <details><summary>事实提取</summary>
                        <p>最后消息：{esc(facts.get('last_customer_msg',''))} ({esc(facts.get('last_customer_msg_time',''))})</p>
                        <p>装修阶段：{esc(facts.get('renovation_stage',''))}</p>
                        <p>核心需求：{esc(facts.get('core_needs',''))}</p>
                        <p>价格讨论：{esc(facts.get('price_discussion',''))}</p>
                        <p>推进动作：{esc(facts.get('progress_actions',''))}</p>
                        <p>情绪走向：{esc(facts.get('emotion_trend',''))}</p>
                    </details>
                    <details><summary>诊断 → {ACTION_CN.get(diag.get('action',''), diag.get('action',''))}</summary>
                        <p>依据：{esc(diag.get('reason',''))}</p>
                        <p>建议：{esc(diag.get('do_this',''))}</p>
                        <p>自我批判：{esc(json.dumps(diag.get('self_critique',[]), ensure_ascii=False))}</p>
                    </details>
                    <details><summary>交叉验证 {'✅' if xval.get('validated') else '❌修正'}</summary>
                        <p>{esc(xval.get('validation_note',''))}</p>
                    </details>
                </div>
                <details class="chat-fold"><summary>聊天记录（{r['msg_count_recent']}条）</summary>
                    <div class="chat-box">{chat_lines}</div>
                </details>
            </div>
        </div>'''

    html = f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<title>T-033 {sales_name} B组四步诊断</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,"Microsoft YaHei",sans-serif;background:#1a1a1a;color:#e0e0e0;padding:16px}}
h1{{color:#E8C47C;font-size:20px;margin-bottom:6px}}
.meta{{color:#999;font-size:12px;margin-bottom:16px}}
table{{border-collapse:collapse;width:100%;margin-bottom:16px;font-size:11px}}
th{{background:#2a2a2a;color:#E8C47C;padding:5px 6px;text-align:left;border:1px solid #333}}
td{{padding:4px 6px;border:1px solid #333}}
tr:hover{{background:#252525}}
a{{color:#E8C47C;text-decoration:none}}
.stats{{display:flex;gap:12px;margin-bottom:16px;flex-wrap:wrap}}
.st{{background:#222;border:1px solid #333;border-radius:6px;padding:10px;min-width:150px}}
.st h3{{color:#E8C47C;font-size:12px;margin-bottom:4px}}
.st .d{{font-size:11px;color:#999}}
.card{{background:#222;border:1px solid #333;border-radius:6px;margin-bottom:12px;overflow:hidden}}
.card-hdr{{background:#2a2a2a;padding:8px 12px;display:flex;align-items:center;flex-wrap:wrap;gap:6px}}
.cn{{color:#E8C47C;font-weight:bold}}
.nm{{font-size:15px;font-weight:bold}}
.wx{{color:#666;font-size:10px;font-family:monospace}}
.act{{background:#333;padding:1px 6px;border-radius:3px;font-size:11px}}
.mt{{color:#777;font-size:11px}}
.card-body{{padding:10px}}
.final-box{{background:#2a1a2a;border:1px solid #4a2a4a;border-radius:6px;padding:10px;margin-bottom:8px;font-size:12px;line-height:1.6}}
details{{margin:4px 0;background:#1a1a2a;border:1px solid #2a2a4a;border-radius:4px;padding:6px}}
summary{{cursor:pointer;color:#E8C47C;font-size:12px;font-weight:bold}}
details p{{font-size:11px;margin:2px 0;line-height:1.5}}
.chat-fold{{background:#1a1a1a;border-color:#333}}
.chat-fold summary{{color:#888}}
.chat-box{{font-size:10px;line-height:1.5;color:#aaa;word-break:break-all;max-height:400px;overflow-y:auto;padding:6px}}
.sec{{color:#E8C47C;font-size:15px;margin:16px 0 8px}}
</style></head><body>

<h1>T-033 {sales_name} — B组四步诊断</h1>
<div class="meta">{datetime.now().strftime('%Y-%m-%d %H:%M')} | Haiku 4.5 Batch | {n}人</div>

<div class="stats">
    <div class="st"><h3>诊断分布</h3><div class="d">{dist_html}</div></div>
    <div class="st"><h3>修正率</h3><div class="d">交叉验证：{xval_corrections}/{n}<br>Monica：{monica_corrections}/{n}</div></div>
    <div class="st"><h3>全部销售汇总</h3><div class="d">{" / ".join(f"{ACTION_CN.get(a,a)}:{global_dist.get(a,0)}" for a in ["rush","follow","revive","nurture","drop"] if global_dist.get(a,0))}<br>共{len(all_results)}人</div></div>
</div>

<h2 class="sec">总表</h2>
<table>
<tr><th>#</th><th>客户</th><th>微信号</th><th>消息</th><th>诊断</th><th>验证</th><th>Monica</th><th>最终</th><th>依据</th><th>建议</th></tr>
{summary_rows}
</table>

<h2 class="sec">详情</h2>
{cards}
</body></html>'''

    path = os.path.join(DIAG_DIR, f'T033-{sales_name}-{n}人-{datetime.now().strftime("%m%d")}.html')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    logger.info(f"HTML: {path}")


if __name__ == '__main__':
    main()
