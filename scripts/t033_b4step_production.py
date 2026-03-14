#!/usr/bin/env python3
"""
T-033 B组四步诊断量产验证
对3位销售近30天活跃客户（排除成交+群聊）执行四步诊断：
  Step1 事实提取 → Step2 诊断+自我批评 → Step3 交叉验证 → Step4 Monica对抗审核
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

# 内部同事/老板/助理的wechat_id（不是客户，不参与诊断）
INTERNAL_IDS = {
    'wxid_am3kdib9tt3722',   # 可欣
    'wxid_p03xoj66oss112',   # 小杰
    'wxid_cbk7hkyyp11t12',   # 霄剑
    'wxid_n98h2ys469bm12',   # Monica老板
    'wxid_aufah51bw9ok22',   # Fiona
    'wxid_blcq5kt11il212',   # 昭文（橙遇助理）
    'wxid_p3cqnq00wpz322',   # 许总/MMMonica
}

# 系统账号
SYSTEM_IDS = {'filehelper', 'weixin'}

# 供应商/物流/工厂/同行 — 昵称关键词匹配
SUPPLIER_KEYWORDS = [
    '皮革', '面料', '客服', '跟单', '海运', '快递', '物流', '制造商',
    '皮业', '五金', '家居-', '家具-', '@openim', '凯特罗格', 'WOWTEX',
    '览秀', '4PX', '巴斯皮革', 'MOTOO', '华达皮业', '米格朵', '唯纳罗木',
    '威赫-小家', '允家家居', '时增皮革', '思千家具', '博简居',
]

TODAY_STR = date.today().strftime('%Y年%m月%d日')


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
    """查询3位销售近30天有私聊消息的客户（排除成交订单、排除群聊）"""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    customers = []

    for sales_id in SALES_IDS:
        sales_name = SALES_NAMES[sales_id]
        # 查近30天有私聊消息的客户wechat_id（去重）
        # Supabase REST API不支持复杂SQL，用RPC或分步查询
        # 先拿近30天该销售的所有私聊客户ID
        page_size = 1000
        all_wechat_ids = set()
        offset = 0
        while True:
            resp = supabase_retry(lambda o=offset: supabase.table('chat_messages').select(
                'wechat_id'
            ).eq('sales_wechat_id', sales_id
            ).eq('is_system_msg', False
            ).gte('sent_at', cutoff
            ).not_.('room_id', 'like', '%@chatroom%'
            ).range(o, o + page_size - 1).execute())
            batch = resp.data or []
            for row in batch:
                all_wechat_ids.add(row['wechat_id'])
            if len(batch) < page_size:
                break
            offset += page_size

        # 查成交订单的客户（排除）
        won_ids = set()
        resp = supabase_retry(lambda: supabase.table('orders').select(
            'wechat_id'
        ).eq('order_stage', 'won').execute())
        for row in (resp.data or []):
            if row.get('wechat_id'):
                won_ids.add(row['wechat_id'])

        # 也排除deposit>1000的（视同成交）
        resp = supabase_retry(lambda: supabase.table('orders').select(
            'wechat_id, amount'
        ).eq('order_stage', 'deposit').execute())
        for row in (resp.data or []):
            if row.get('wechat_id') and row.get('amount') and float(row['amount']) > 1000:
                won_ids.add(row['wechat_id'])

        active_ids = all_wechat_ids - won_ids - INTERNAL_IDS - SYSTEM_IDS

        # 排除供应商/物流：查contacts表昵称，匹配关键词的排掉
        supplier_ids = set()
        no_contact_ids = set()
        for wid in list(active_ids):
            contact = supabase_retry(lambda w=wid: supabase.table('contacts').select(
                'nickname, remark'
            ).eq('wechat_id', w).eq('sales_wechat_id', sales_id).limit(1).execute())
            if not contact.data:
                no_contact_ids.add(wid)
                continue
            nickname = (contact.data[0].get('nickname') or '').strip()
            remark = (contact.data[0].get('remark') or '').strip()
            # @openim 格式的ID是云客内部通讯，不是微信客户
            if '@openim' in wid:
                supplier_ids.add(wid)
                continue
            # 昵称/备注匹配供应商关键词
            combined = nickname + remark
            for kw in SUPPLIER_KEYWORDS:
                if kw in combined:
                    supplier_ids.add(wid)
                    logger.info(f"    排除供应商: {nickname} ({remark}) 匹配'{kw}'")
                    break

        active_ids = active_ids - supplier_ids - no_contact_ids
        n_excluded = len(won_ids & all_wechat_ids)
        n_internal = len((INTERNAL_IDS | SYSTEM_IDS) & all_wechat_ids)
        logger.info(f"  {sales_name}: 近30天私聊{len(all_wechat_ids)}人, "
                     f"排除成交{n_excluded}+内部{n_internal}+供应商{len(supplier_ids)}+无记录{len(no_contact_ids)} → 剩余{len(active_ids)}人")

        for wid in active_ids:
            customers.append((wid, sales_id))

    logger.info(f"总计待诊断客户: {len(customers)}人")
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
        logger.warning(f"  {label} JSON解析失败, 原文前200字: {text[:200]}")
    return {'_raw': text, '_parse_error': True}


# ============ API ============
def call_haiku(prompt, max_tokens=512):
    resp = claude.messages.create(
        model=HAIKU, max_tokens=max_tokens,
        messages=[{'role': 'user', 'content': prompt}],
    )
    raw = ''.join(b.text for b in resp.content if hasattr(b, 'text'))
    cost = (resp.usage.input_tokens * 1.0 + resp.usage.output_tokens * 5.0) / 1_000_000
    return raw, cost, resp.usage.input_tokens, resp.usage.output_tokens


# ============ B组四步诊断 ============
def b4step_diagnose(nickname, remark, msg_count, customer_count, sales_count,
                    order_stage, chat_text, recent_count):
    """B组四步: 事实提取→诊断+自我批评→交叉验证→Monica对抗审核"""
    results = {}
    total_cost = 0

    # Step 1: 事实提取
    fact_prompt = f"""你是莫妮卡摩卡高定家具品牌的数据分析师。请从以下聊天记录中提取恰好6项事实。

客户：{nickname}，备注：{remark}，消息{msg_count}条（客户{customer_count}/销售{sales_count}），订单：{order_stage}

聊天记录（{recent_count}条）：
{chat_text}

请严格按JSON输出：
{{
  "last_customer_msg": "客户最后一条主动消息的原文（非群发）",
  "last_customer_msg_time": "该消息的时间（mm-dd HH:MM格式）",
  "renovation_stage": "装修阶段（引用原文证据，如'客户说还没交房'。无证据写'未提及'）",
  "core_needs": "核心需求/顾虑（如'想买岩石沙发3米，担心面料掉色'。无明确需求写'未明确'）",
  "price_discussion": "价格讨论情况（如'报价21850，客户说贵了'。未讨论价格写'未报价'）",
  "progress_actions": "推进动作（报价/寄样/到访/拉群等，列举已发生的。无则写'无'）",
  "emotion_trend": "客户情绪走向（热→冷/冷→热/持平/无法判断，引用证据）"
}}
只输出JSON，不要其他内容。"""

    raw1, cost1, _, _ = call_haiku(fact_prompt, 512)
    total_cost += cost1
    facts = parse_json_response(raw1, 'Step1事实提取')
    results['facts'] = facts
    time.sleep(0.3)

    # Step 2: 诊断+自我批评
    facts_text = json.dumps(facts, ensure_ascii=False, indent=2) if not facts.get('_parse_error') else raw1

    diag_prompt = f"""你是莫妮卡摩卡的销售诊断AI。基于以下事实清单，判断客户应该用哪个动作跟进。

⚠️ 今天的日期是 {TODAY_STR}。计算沉默天数时必须用今天的日期减去客户最后消息日期。

## 事实清单
{facts_text}

## 客户基本信息
昵称：{nickname}，备注：{remark}，消息{msg_count}条（客户{customer_count}/销售{sales_count}），订单：{order_stage}

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
范例1：客户3月1日问"定金多少"，销售至今未回复（13天） → {{"action":"rush","reason":"销售漏回复客户定金问题","do_this":"立即回复定金流程，发岩石沙发报价单","risk":null}}
范例2：客户沉默5个月，期间销售群发3次无回应 → {{"action":"drop","reason":"沉默超90天，大概率已购买","do_this":"不主动跟进","risk":null}}
范例3：客户讨论过面料和尺寸，2天前销售报价后未回 → {{"action":"follow","reason":"报价后沉默，客户之前态度积极","do_this":"发岩石沙发棉麻实拍对比图，问客户倾向","risk":"报价后沉默"}}
范例4：客户要买餐桌椅，非我们品类 → {{"action":"revive","reason":"非品类需求，但有家具购买意向","do_this":"发产品线介绍，引导关注沙发系列","risk":null}}

请输出JSON：
{{
  "action": "rush/follow/revive/nurture/drop",
  "reason": "20字内",
  "do_this": "50字内",
  "risk": "没有则null",
  "self_critique": ["可能错的原因1", "可能错的原因2", "可能错的原因3"]
}}
只输出JSON。"""

    raw2, cost2, _, _ = call_haiku(diag_prompt, 512)
    total_cost += cost2
    diag = parse_json_response(raw2, 'Step2诊断')
    results['diag'] = diag
    time.sleep(0.3)

    # Step 3: 交叉验证
    action = diag.get('action', '?')
    reason = diag.get('reason', '')
    do_this_val = diag.get('do_this', '')
    risk = diag.get('risk')
    critique = diag.get('self_critique', [])

    xval_prompt = f"""你是莫妮卡摩卡的诊断质检员。以下是对客户"{nickname}"的诊断结果和事实清单。请检查诊断是否有遗漏或矛盾。

诊断结果：
- 动作：{ACTION_CN.get(action, action)}（{action}）
- 原因：{reason}
- 建议：{do_this_val}
- 风险：{risk or '无'}
- AI自己列的可能错误：{json.dumps(critique, ensure_ascii=False)}

事实清单：
{facts_text}

原始聊天记录（{recent_count}条）：
{chat_text}

请检查：
1. 事实清单是否遗漏了聊天记录中的重要信息？
2. 诊断动作是否与事实矛盾？
3. AI自己列的可能错误，是否确实存在？

如果发现问题需要修正，输出修正后的JSON；如果没问题，原样返回：
{{
  "validated": true或false,
  "action": "{action}",
  "reason": "20字内",
  "do_this": "50字内",
  "risk": null或"15字内",
  "validation_note": "检查结论（1-2句话）"
}}
只输出JSON。"""

    raw3, cost3, _, _ = call_haiku(xval_prompt, 512)
    total_cost += cost3
    xval = parse_json_response(raw3, 'Step3交叉验证')
    results['xval'] = xval
    time.sleep(0.3)

    # Step 4: Monica对抗审核
    xval_action = xval.get('action', action)
    xval_reason = xval.get('reason', reason)
    xval_do_this = xval.get('do_this', do_this_val)
    xval_risk = xval.get('risk', risk)

    monica_prompt = f"""你是Monica，莫妮卡摩卡的老板。你最讨厌AI把所有客户都判rush浪费销售精力，也讨厌把有价值客户判drop错过机会。

以下是AI对客户"{nickname}"的最终诊断：
- 动作：{ACTION_CN.get(xval_action, xval_action)}
- 原因：{xval_reason}
- 建议：{xval_do_this}
- 风险：{xval_risk or '无'}

客户基本信息：备注{remark}，消息{msg_count}条（客户{customer_count}/销售{sales_count}），订单{order_stage}

聊天记录（{recent_count}条）：
{chat_text}

强制二选一——这个诊断你是否同意？
- 同意：原样返回JSON
- 不同意：给出你的修正

输出JSON：
{{
  "agree": true或false,
  "action": "rush/follow/revive/nurture/drop",
  "reason": "20字内",
  "do_this": "50字内",
  "risk": "没有则null",
  "monica_note": "Monica的判断理由（1句话）"
}}
只输出JSON。"""

    raw4, cost4, _, _ = call_haiku(monica_prompt, 512)
    total_cost += cost4
    monica = parse_json_response(raw4, 'Step4Monica审核')
    results['monica'] = monica

    return results, total_cost


# ============ Main ============
def main():
    logger.info("=" * 60)
    logger.info("T-033 B组四步诊断量产验证")
    logger.info("=" * 60)

    # 查询活跃客户
    customers = fetch_active_customers()
    if not customers:
        logger.error("未查询到活跃客户")
        return

    results = []
    total_cost = 0
    skipped = 0
    errors = 0
    start_time = time.time()

    for i, (contact_id, sales_id) in enumerate(customers):
        sales_name = SALES_NAMES.get(sales_id, sales_id)

        # 查联系人信息
        contact = supabase_retry(lambda: supabase.table('contacts').select(
            'nickname, remark, wechat_alias, has_quote, add_time'
        ).eq('wechat_id', contact_id).eq('sales_wechat_id', sales_id).limit(1).execute())
        if not contact.data:
            skipped += 1
            continue

        c = contact.data[0]
        nickname = c.get('nickname', '未知')
        remark = c.get('remark', '') or ''
        wechat_alias = c.get('wechat_alias', '') or ''
        add_time = c.get('add_time', '') or ''

        # 拉聊天记录（私聊）
        msgs = fetch_chat_history(contact_id, sales_id)
        if not msgs:
            skipped += 1
            continue

        chat_text, msg_count_recent = build_chat_text(msgs)
        customer_count = sum(1 for m in msgs if m.get('sender_type') != 'sales')
        sales_count_val = len(msgs) - customer_count

        # 查订单
        order = supabase_retry(lambda: supabase.table('orders').select('order_stage').eq(
            'wechat_id', contact_id).limit(1).execute())
        if not order.data and wechat_alias and wechat_alias != contact_id:
            order = supabase_retry(lambda: supabase.table('orders').select('order_stage').eq(
                'wechat_id', wechat_alias).limit(1).execute())
        order_stage = order.data[0]['order_stage'] if order.data else '无'

        elapsed_total = time.time() - start_time
        eta = (elapsed_total / (i + 1)) * (len(customers) - i - 1) if i > 0 else 0
        logger.info(f"[{i+1}/{len(customers)}] {nickname} ({sales_name}) {len(msgs)}条消息 | 已用{elapsed_total/60:.0f}分 预计剩{eta/60:.0f}分")

        try:
            t0 = time.time()
            b_result, cost = b4step_diagnose(
                nickname, remark, len(msgs), customer_count, sales_count_val,
                order_stage, chat_text, msg_count_recent
            )
            elapsed = time.time() - t0
            total_cost += cost

            final_action = b_result.get('monica', {}).get('action', b_result.get('diag', {}).get('action', '?'))
            logger.info(f"  → {ACTION_CN.get(final_action, final_action)} ¥{cost*7.2:.3f} {elapsed:.1f}秒")

            results.append({
                'nickname': nickname, 'wechat_alias': wechat_alias, 'sales': sales_name,
                'sales_id': sales_id, 'contact_id': contact_id,
                'remark': remark, 'add_time': add_time,
                'msg_total': len(msgs), 'msg_customer': customer_count,
                'msg_sales': sales_count_val, 'order_stage': order_stage,
                'chat_text': chat_text, 'msg_count_recent': msg_count_recent,
                'b4step': b_result, 'cost': cost, 'elapsed': elapsed,
            })
        except Exception as e:
            errors += 1
            logger.error(f"  诊断失败: {e}")
            traceback.print_exc()
            # 失败也记录
            results.append({
                'nickname': nickname, 'wechat_alias': wechat_alias, 'sales': sales_name,
                'sales_id': sales_id, 'contact_id': contact_id,
                'remark': remark, 'add_time': add_time,
                'msg_total': len(msgs), 'msg_customer': customer_count,
                'msg_sales': sales_count_val, 'order_stage': order_stage,
                'chat_text': '', 'msg_count_recent': 0,
                'b4step': None, 'cost': 0, 'elapsed': 0, 'error': str(e),
            })

    total_elapsed = time.time() - start_time
    logger.info(f"\n完成: {len(results)}人诊断, {skipped}跳过, {errors}失败")
    logger.info(f"总耗时: {total_elapsed/60:.1f}分, 总成本: ¥{total_cost*7.2:.2f}")

    generate_report(results, total_cost, skipped, errors, total_elapsed)


# ============ HTML Report ============
def generate_report(results, total_cost, skipped, errors, total_elapsed):
    import html as html_mod

    def esc(s):
        return html_mod.escape(str(s)) if s else ''

    # 统计
    valid = [r for r in results if r.get('b4step')]
    n = len(valid) or 1

    # 按销售统计
    by_sales = {}
    action_dist = {}
    for r in valid:
        s = r['sales']
        if s not in by_sales:
            by_sales[s] = {'total': 0, 'actions': {}}
        by_sales[s]['total'] += 1
        final = r['b4step'].get('monica', {}).get('action', r['b4step'].get('diag', {}).get('action', '?'))
        action_dist[final] = action_dist.get(final, 0) + 1
        by_sales[s]['actions'][final] = by_sales[s]['actions'].get(final, 0) + 1

    dist_html = ' / '.join(f'{ACTION_CN.get(a,a)}: {action_dist.get(a,0)}'
                           for a in ['rush','follow','revive','nurture','drop'] if action_dist.get(a,0))

    # 按销售分布
    sales_dist_html = ''
    for s in ['可欣', '小杰', '霄剑']:
        if s in by_sales:
            info = by_sales[s]
            acts = ' / '.join(f'{ACTION_CN.get(a,a)}:{info["actions"].get(a,0)}'
                              for a in ['rush','follow','revive','nurture','drop'] if info['actions'].get(a,0))
            sales_dist_html += f'<div class="stat-card"><h3>{s} ({info["total"]}人)</h3><div class="detail">{acts}</div></div>'

    # Monica修正率
    monica_corrections = sum(1 for r in valid if not r['b4step'].get('monica', {}).get('agree', True))
    xval_corrections = sum(1 for r in valid if not r['b4step'].get('xval', {}).get('validated', True))

    # 总表
    summary_rows = ''
    for idx, r in enumerate(valid):
        b = r.get('b4step') or {}
        monica = b.get('monica', {})
        diag = b.get('diag', {})
        xval = b.get('xval', {})
        # 各步骤action
        diag_action = diag.get('action', '?')
        xval_action = xval.get('action', diag_action)
        final_action = monica.get('action', xval_action)

        # 变化标记
        changed_xval = '→' + ACTION_CN.get(xval_action, xval_action) if xval_action != diag_action else '✅'
        changed_monica = '→' + ACTION_CN.get(final_action, final_action) if not monica.get('agree', True) else '✅'

        summary_rows += f'''<tr>
            <td>{idx+1}</td>
            <td><a href="#c{idx}">{esc(r["nickname"])}</a></td>
            <td>{esc(r.get("wechat_alias",""))}</td>
            <td>{esc(r["sales"])}</td>
            <td>{r["msg_total"]}</td>
            <td>{ACTION_CN.get(diag_action, diag_action)}</td>
            <td>{changed_xval}</td>
            <td>{changed_monica}</td>
            <td>{ACTION_CN.get(final_action, final_action)}</td>
            <td style="font-size:10px;color:#999">{r.get("elapsed",0):.0f}秒</td>
        </tr>\n'''

    # 详情卡片
    customer_cards = ''
    for idx, r in enumerate(valid):
        b = r.get('b4step') or {}
        facts = b.get('facts', {})
        diag = b.get('diag', {})
        xval = b.get('xval', {})
        monica = b.get('monica', {})
        final_action = monica.get('action', xval.get('action', diag.get('action', '?')))

        chat_lines = esc(r.get('chat_text', '')).replace('\n', '<br>')

        customer_cards += f'''
        <div class="customer-card" id="c{idx}">
            <div class="card-header">
                <span class="card-num">#{idx+1}</span>
                <span class="card-name">{esc(r['nickname'])}</span>
                <span class="card-sales">({esc(r['sales'])})</span>
                <span class="card-wxid">{esc(r.get('wechat_alias',''))}</span>
                <span class="card-action">{ACTION_CN.get(final_action, final_action)}</span>
                <span class="card-meta">备注:{esc(r.get('remark') or '无')} | 消息:{r.get('msg_total',0)}条(客{r.get('msg_customer',0)}/销{r.get('msg_sales',0)}) | 订单:{esc(r.get('order_stage') or '无')}</span>
            </div>
            <div class="two-col">
                <div class="col-left">
                    <h4>聊天记录（共{r.get('msg_count_recent',0)}条）</h4>
                    <div class="chat-box">{chat_lines}</div>
                </div>
                <div class="col-right">
                    <details open><summary>步骤1 事实提取</summary>
                        <p>最后消息：{esc(facts.get('last_customer_msg',''))} ({esc(facts.get('last_customer_msg_time',''))})</p>
                        <p>装修阶段：{esc(facts.get('renovation_stage',''))}</p>
                        <p>核心需求：{esc(facts.get('core_needs',''))}</p>
                        <p>价格讨论：{esc(facts.get('price_discussion',''))}</p>
                        <p>推进动作：{esc(facts.get('progress_actions',''))}</p>
                        <p>情绪走向：{esc(facts.get('emotion_trend',''))}</p>
                    </details>
                    <details><summary>步骤2 诊断+自我批判 → {ACTION_CN.get(diag.get('action',''), diag.get('action',''))}</summary>
                        <p>依据：{esc(diag.get('reason',''))}</p>
                        <p>建议：{esc(diag.get('do_this',''))}</p>
                        <p>风险：{esc(diag.get('risk') or '无')}</p>
                        <p style="color:#888;font-size:11px">自我批判：{esc(json.dumps(diag.get('self_critique',[]), ensure_ascii=False))}</p>
                    </details>
                    <details><summary>步骤3 交叉验证 {'✅通过' if xval.get('validated') else '❌修正→' + ACTION_CN.get(xval.get('action',''), xval.get('action',''))}</summary>
                        <p>动作：{ACTION_CN.get(xval.get('action',''), xval.get('action',''))}</p>
                        <p>依据：{esc(xval.get('reason',''))}</p>
                        <p>建议：{esc(xval.get('do_this',''))}</p>
                        <p>说明：{esc(xval.get('validation_note',''))}</p>
                    </details>
                    <div class="monica-box">
                        <h4>步骤4 Monica审核 {'✅同意' if monica.get('agree') else '❌修正'}</h4>
                        <p><b>最终动作：</b>{ACTION_CN.get(final_action, final_action)}</p>
                        <p><b>依据：</b>{esc(monica.get('reason',''))}</p>
                        <p><b>建议：</b>{esc(monica.get('do_this',''))}</p>
                        <p><b>风险：</b>{esc(monica.get('risk') or '无')}</p>
                        <p style="color:#CE93D8;font-size:12px">{esc(monica.get('monica_note',''))}</p>
                    </div>
                </div>
            </div>
        </div>
        '''

    # 失败的客户
    failed = [r for r in results if not r.get('b4step')]
    failed_html = ''
    if failed:
        failed_rows = ''.join(f'<tr><td>{esc(r["nickname"])}</td><td>{esc(r["sales"])}</td><td>{esc(r.get("error",""))}</td></tr>'
                               for r in failed)
        failed_html = f'''<h2 class="section-title">诊断失败 ({len(failed)}人)</h2>
        <table><tr><th>客户</th><th>销售</th><th>错误</th></tr>{failed_rows}</table>'''

    avg_cost = total_cost / n
    avg_time = sum(r.get('elapsed', 0) for r in valid) / n

    html_content = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>T-033 B组四步诊断量产验证</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, "Microsoft YaHei", sans-serif; background:#1a1a1a; color:#e0e0e0; padding:20px; }}
h1 {{ color:#E8C47C; margin-bottom:8px; font-size:22px; }}
.meta {{ color:#999; font-size:13px; margin-bottom:20px; }}
table {{ border-collapse:collapse; width:100%; margin-bottom:20px; font-size:12px; }}
th {{ background:#2a2a2a; color:#E8C47C; padding:6px 8px; text-align:left; border:1px solid #333; }}
td {{ padding:5px 8px; border:1px solid #333; }}
tr:hover {{ background:#252525; }}
a {{ color:#E8C47C; text-decoration:none; }}
.stats-grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr)); gap:12px; margin-bottom:20px; }}
.stat-card {{ background:#222; border:1px solid #333; border-radius:8px; padding:12px; }}
.stat-card h3 {{ color:#E8C47C; font-size:13px; margin-bottom:6px; }}
.stat-card .num {{ font-size:24px; font-weight:bold; color:#fff; }}
.stat-card .detail {{ font-size:11px; color:#999; margin-top:4px; }}
.customer-card {{ background:#222; border:1px solid #333; border-radius:8px; margin-bottom:16px; overflow:hidden; }}
.card-header {{ background:#2a2a2a; padding:10px 15px; border-bottom:1px solid #333; display:flex; align-items:center; flex-wrap:wrap; gap:8px; }}
.card-num {{ color:#E8C47C; font-weight:bold; }}
.card-name {{ font-size:16px; font-weight:bold; }}
.card-sales {{ color:#999; }}
.card-wxid {{ color:#666; font-size:11px; font-family:monospace; }}
.card-action {{ background:#333; padding:2px 8px; border-radius:4px; font-size:12px; }}
.card-meta {{ color:#777; font-size:12px; }}
.two-col {{ display:grid; grid-template-columns:1fr 1fr; min-height:200px; }}
.col-left {{ border-right:1px solid #333; padding:12px; overflow-y:auto; max-height:500px; }}
.col-left h4 {{ color:#E8C47C; font-size:13px; margin-bottom:8px; }}
.chat-box {{ font-size:11px; line-height:1.6; color:#ccc; word-break:break-all; }}
.col-right {{ padding:12px; overflow-y:auto; max-height:500px; }}
.col-right details {{ margin:6px 0; background:#1a1a2a; border:1px solid #2a2a4a; border-radius:6px; padding:8px; }}
.col-right summary {{ cursor:pointer; color:#E8C47C; font-size:13px; font-weight:bold; }}
.col-right details p {{ font-size:12px; margin:3px 0; line-height:1.5; }}
.monica-box {{ background:#2a1a2a; border:1px solid #4a2a4a; border-radius:6px; padding:10px; margin-top:8px; }}
.monica-box h4 {{ color:#CE93D8; font-size:14px; margin-bottom:6px; }}
.monica-box p {{ font-size:12px; margin-bottom:3px; }}
.section-title {{ color:#E8C47C; font-size:16px; margin:20px 0 10px; }}
</style>
</head>
<body>

<h1>T-033 B组四步诊断量产验证</h1>
<div class="meta">
    测试时间：{datetime.now().strftime('%Y-%m-%d %H:%M')} | 模型：Haiku 4.5 |
    客户：{len(valid)}人（跳过{skipped}，失败{errors}） |
    总耗时：{total_elapsed/60:.1f}分 | 总成本：¥{total_cost*7.2:.2f}
</div>

<div class="stats-grid">
    <div class="stat-card">
        <h3>诊断分布（最终结果）</h3>
        <div class="detail">{dist_html}</div>
    </div>
    <div class="stat-card">
        <h3>单客户成本/耗时</h3>
        <div class="num">¥{avg_cost*7.2:.3f}</div>
        <div class="detail">均耗时 {avg_time:.1f}秒 | 4次Haiku调用/人</div>
    </div>
    <div class="stat-card">
        <h3>修正率</h3>
        <div class="detail">交叉验证修正：{xval_corrections}/{len(valid)} ({xval_corrections/n*100:.0f}%)<br>Monica修正：{monica_corrections}/{len(valid)} ({monica_corrections/n*100:.0f}%)</div>
    </div>
    {sales_dist_html}
</div>

<h2 class="section-title">逐条总表</h2>
<table>
<tr><th>#</th><th>客户</th><th>微信号</th><th>销售</th><th>消息</th><th>Step2诊断</th><th>Step3验证</th><th>Step4 Monica</th><th>最终</th><th>耗时</th></tr>
{summary_rows}
</table>

{failed_html}

<h2 class="section-title">逐客户详情</h2>
{customer_cards}

</body>
</html>'''

    diag_dir = os.path.join(os.path.expanduser('~'), 'Desktop', '诊断结果')
    os.makedirs(diag_dir, exist_ok=True)
    output = os.path.join(diag_dir, f'T033-B四步量产-{len(valid)}人-{datetime.now().strftime("%m%d-%H%M")}.html')
    with open(output, 'w', encoding='utf-8') as f:
        f.write(html_content)
    logger.info(f"报告: {output}")

    # 同时保存JSON原始数据（方便后续分析）
    json_output = output.replace('.html', '.json')
    json_data = []
    for r in valid:
        jr = {k: v for k, v in r.items() if k != 'chat_text'}
        jr['chat_msg_count'] = r.get('msg_count_recent', 0)
        json_data.append(jr)
    with open(json_output, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    logger.info(f"原始数据: {json_output}")


if __name__ == '__main__':
    main()
