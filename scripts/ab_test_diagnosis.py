#!/usr/bin/env python3
"""
T-023: AI诊断A/B测试 — 三模型对比（DeepSeek V3.2 / Haiku 4.5 / Sonnet 4.6）

对50个分层抽样客户，分别用三个模型跑诊断，对比输出质量和成本。
分层：深度(≥30条)10人、中等(10-29条)15人、浅度(3-9条)15人、已报价10人
每层按三个销售（小杰/可欣/霄剑）均匀分配。

用法：
  python ab_test_diagnosis.py --select      # 只做客户抽样，输出候选列表
  python ab_test_diagnosis.py --run         # 执行全部三个模型诊断
  python ab_test_diagnosis.py --run --model deepseek   # 只跑DeepSeek
  python ab_test_diagnosis.py --run --model haiku      # 只跑Haiku
  python ab_test_diagnosis.py --run --model sonnet     # 只跑Sonnet
  python ab_test_diagnosis.py --report      # 生成对比报告
"""

import os
import sys
import json
import time
import random
import argparse
import logging
from datetime import datetime, timezone
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

# ============ 销售配置（只取参与测试的3位） ============
TEST_SALES = {
    'wxid_p03xoj66oss112': '小杰',
    'wxid_am3kdib9tt3722': '可欣',
    'wxid_cbk7hkyyp11t12': '霄剑',
}

# ============ 分层抽样配置 ============
STRATA = {
    'deep':   {'min_msgs': 30, 'max_msgs': 999999, 'count': 10, 'has_quote': None},
    'medium': {'min_msgs': 10, 'max_msgs': 29,     'count': 15, 'has_quote': None},
    'shallow':{'min_msgs': 3,  'max_msgs': 9,      'count': 15, 'has_quote': None},
    'quoted': {'min_msgs': 0,  'max_msgs': 999999, 'count': 10, 'has_quote': True},
}

# ============ 模型配置 ============
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', '')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')

MODELS = {
    'deepseek': {
        'name': 'DeepSeek V3.2 (reasoner)',
        'model_id': 'deepseek-reasoner',
        'base_url': 'https://api.deepseek.com',
        'price_input': 0.28,   # $/M tokens
        'price_output': 0.42,  # $/M tokens
    },
    'haiku': {
        'name': 'Claude Haiku 4.5',
        'model_id': 'claude-haiku-4-5-20251001',
        'price_input': 1.00,
        'price_output': 5.00,
    },
    'sonnet': {
        'name': 'Claude Sonnet 4.6',
        'model_id': 'claude-sonnet-4-6',
        'price_input': 3.00,
        'price_output': 15.00,
    },
}

# ============ 共用Prompt模板 ============
DIAGNOSIS_PROMPT = """你是高端定制家具品牌"莫妮卡摩卡"的销售分析AI。客户通过微信私域沟通，产品为岩石沙发、像素沙发、模块沙发等定制家具，客单价2-8万元。

请分析以下客户的聊天记录，输出JSON格式（不要输出其他内容，不要用markdown包裹）：
{{
  "action": "rush|revive|nurture|drop",
  "reason": "你判断的核心依据（一句话，20字内）",
  "do_this": "下一步具体动作（一句话，30字内，销售能直接执行）",
  "risk": "流失风险信号（没有则为null，15字内）"
}}

action必须是以下4个之一：
- rush：客户有明确推进信号（主动问价/问尺寸/要地址/确认面料/谈定金），销售应立刻回复
- revive：客户沉默了但之前有深度互动或报过价，值得主动激活
- nurture：浅度接触或装修早期，时机没到，低频维护即可
- drop：明确拒绝/预算严重不匹配/已在别家购买，不再主动跟进

关键判断规则：
1. 客户说"已经买了/订好了/找别家了"且聊天中没有本品牌付款/发货记录 → 必须判drop，不是成交
2. 客户最后一条消息是主动询问（价格/尺寸/面料/地址）→ rush，不管沉默多久
3. 沉默>14天但历史聊天>=15条或has_quote=true → revive
4. 沉默>14天且历史聊天<15条 → nurture
5. 预算明确低于产品定价50%以上 → drop
6. do_this必须具体到产品/场景，禁止写"保持跟进""发送优惠"等空话

客户信息：
- 备注名：{remark}
- 加微时间：{add_time}
- 聊天总条数：{msg_count}
- 是否报过价：{has_quote}

聊天记录（最近50条，从旧到新）：
{conversation}"""

# ============ 结果文件路径 ============
RESULTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'ab_test')
SAMPLE_FILE = os.path.join(RESULTS_DIR, 'sample_customers.json')
INPUT_FILE = os.path.join(RESULTS_DIR, 'input_data.json')


def ensure_results_dir():
    os.makedirs(RESULTS_DIR, exist_ok=True)


# ========================================================================
# Step 1: 分层抽样选50个客户
# ========================================================================
def select_customers():
    """分层抽样选取50个测试客户"""
    logger.info("=== Step 1: 分层抽样选取测试客户 ===")

    # 1. 获取已成交客户（排除）— 生产表用 wechat_id + order_stage='won'
    #    注：orders表无sales_wechat_id，只用wechat_id排除
    logger.info("获取已成交客户列表...")
    won_wechat_ids = set()
    offset = 0
    while True:
        result = supabase.table('orders').select(
            'wechat_id'
        ).eq('order_stage', 'won').range(offset, offset + 999).execute()
        if not result.data:
            break
        for row in result.data:
            wid = row.get('wechat_id')
            if wid:
                won_wechat_ids.add(wid)
        if len(result.data) < 1000:
            break
        offset += 1000
    logger.info(f"已成交客户wechat_id数: {len(won_wechat_ids)}")

    # 2. 获取所有contacts（3位销售的私聊好友）
    logger.info("获取contacts...")
    all_contacts = []
    for sales_wx in TEST_SALES:
        offset = 0
        while True:
            result = supabase.table('contacts').select(
                'wechat_id, sales_wechat_id, nickname, remark, has_quote'
            ).eq('is_deleted', 0).eq(
                'sales_wechat_id', sales_wx
            ).neq('friend_type', 2).range(offset, offset + 999).execute()
            if not result.data:
                break
            all_contacts.extend(result.data)
            if len(result.data) < 1000:
                break
            offset += 1000
    logger.info(f"3位销售的contacts总数: {len(all_contacts)}")

    # 3. 统计每个客户的私聊非系统消息条数
    #    优化：按销售拉全部私聊消息的(wechat_id)，在本地计数，避免N次API调用
    logger.info("统计每个客户私聊消息条数（按销售批量拉取）...")
    msg_counts = defaultdict(int)  # key: (wechat_id, sales_wechat_id) -> count

    for sales_wx in TEST_SALES:
        logger.info(f"  拉取 {TEST_SALES[sales_wx]} 的私聊消息...")
        offset = 0
        page_size = 1000
        while True:
            result = supabase.table('chat_messages').select(
                'wechat_id'
            ).eq(
                'sales_wechat_id', sales_wx
            ).eq(
                'is_system_msg', False
            ).not_.like('room_id', '%@chatroom').range(
                offset, offset + page_size - 1
            ).execute()
            if not result.data:
                break
            for row in result.data:
                wid = row.get('wechat_id')
                if wid:
                    msg_counts[(wid, sales_wx)] += 1
            if len(result.data) < page_size:
                break
            offset += page_size
        logger.info(f"    累计客户数: {sum(1 for k in msg_counts if k[1] == sales_wx)}")

    # 构建候选列表
    contacts_map = {}
    for c in all_contacts:
        key = (c['wechat_id'], c['sales_wechat_id'])
        contacts_map[key] = c

    contact_msg_counts = {}
    for key, cnt in msg_counts.items():
        if key[0] in won_wechat_ids:
            continue  # 排除已成交
        c = contacts_map.get(key)
        if not c:
            continue  # 不在contacts中（可能是群消息泄漏）
        if cnt > 0:
            contact_msg_counts[key] = {
                'wechat_id': c['wechat_id'],
                'sales_wechat_id': c['sales_wechat_id'],
                'nickname': c.get('nickname', ''),
                'remark': c.get('remark', ''),
                'has_quote': c.get('has_quote', False) or False,
                'msg_count': cnt,
            }
    logger.info(f"有聊天记录的客户数: {len(contact_msg_counts)}")

    # 4. 分层
    pools = {stratum: defaultdict(list) for stratum in STRATA}
    for key, info in contact_msg_counts.items():
        sales_wx = info['sales_wechat_id']
        cnt = info['msg_count']
        has_q = info['has_quote']

        # 已报价层（优先归入）
        if has_q:
            pools['quoted'][sales_wx].append(info)
        # 按消息数分层（已报价的也参与其他层候选，但优先已报价层）
        if cnt >= 30:
            pools['deep'][sales_wx].append(info)
        elif cnt >= 10:
            pools['medium'][sales_wx].append(info)
        elif cnt >= 3:
            pools['shallow'][sales_wx].append(info)

    # 打印各层各销售候选数
    for stratum, by_sales in pools.items():
        counts = {TEST_SALES.get(s, s): len(lst) for s, lst in by_sales.items()}
        logger.info(f"  {stratum}: {counts}")

    # 5. 分层均匀抽样
    random.seed(2026_03_12)  # 固定种子确保可复现
    selected = []
    already_picked = set()  # 避免同一客户被多层重复选

    for stratum, config in STRATA.items():
        target = config['count']
        sales_list = list(TEST_SALES.keys())
        per_sales = target // len(sales_list)  # 每个销售基础数
        remainder = target % len(sales_list)

        stratum_selected = []
        for idx, sales_wx in enumerate(sales_list):
            need = per_sales + (1 if idx < remainder else 0)
            candidates = [
                c for c in pools[stratum].get(sales_wx, [])
                if (c['wechat_id'], c['sales_wechat_id']) not in already_picked
            ]
            random.shuffle(candidates)
            picked = candidates[:need]
            for p in picked:
                already_picked.add((p['wechat_id'], p['sales_wechat_id']))
            stratum_selected.extend(picked)

        # 如果某个销售候选不够，从其他销售补
        if len(stratum_selected) < target:
            shortfall = target - len(stratum_selected)
            all_remaining = []
            for sales_wx in sales_list:
                all_remaining.extend([
                    c for c in pools[stratum].get(sales_wx, [])
                    if (c['wechat_id'], c['sales_wechat_id']) not in already_picked
                ])
            random.shuffle(all_remaining)
            extra = all_remaining[:shortfall]
            for p in extra:
                already_picked.add((p['wechat_id'], p['sales_wechat_id']))
            stratum_selected.extend(extra)

        for item in stratum_selected:
            item['stratum'] = stratum
        selected.extend(stratum_selected)
        logger.info(f"  {stratum}层选中: {len(stratum_selected)}/{target}")

    logger.info(f"总选中客户: {len(selected)}")

    # 保存
    ensure_results_dir()
    with open(SAMPLE_FILE, 'w', encoding='utf-8') as f:
        json.dump(selected, f, ensure_ascii=False, indent=2)
    logger.info(f"样本保存到: {SAMPLE_FILE}")
    return selected


# ========================================================================
# Step 2: 准备输入数据（拉聊天记录）
# ========================================================================
def prepare_input_data(customers=None):
    """为每个客户准备最近50条聊天记录"""
    if customers is None:
        if not os.path.exists(SAMPLE_FILE):
            logger.error("样本文件不存在，请先运行 --select")
            sys.exit(1)
        with open(SAMPLE_FILE, 'r', encoding='utf-8') as f:
            customers = json.load(f)

    logger.info(f"=== Step 2: 准备 {len(customers)} 个客户的聊天记录 ===")
    input_data = []

    for i, c in enumerate(customers):
        wechat_id = c['wechat_id']
        sales_wechat_id = c['sales_wechat_id']
        logger.info(f"  [{i+1}/{len(customers)}] {c.get('remark') or c.get('nickname', wechat_id)}")

        # 取最近50条非系统私聊消息
        result = supabase.table('chat_messages').select(
            'sender_type, content, sent_at, msg_type'
        ).eq('wechat_id', wechat_id).eq(
            'sales_wechat_id', sales_wechat_id
        ).eq('is_system_msg', False).not_.like(
            'room_id', '%@chatroom'
        ).order('sent_at', desc=True).limit(50).execute()

        messages = list(reversed(result.data)) if result.data else []

        # 拼接对话格式
        conversation_lines = []
        for msg in messages:
            role = '销售' if msg.get('sender_type') == 'sales' else '客户'
            sent_at = msg.get('sent_at', '')
            # 格式化时间：取 MM-DD HH:MM
            time_str = ''
            if sent_at:
                try:
                    dt = datetime.fromisoformat(sent_at.replace('Z', '+00:00'))
                    time_str = dt.strftime('%m-%d %H:%M')
                except Exception:
                    time_str = sent_at[:16] if len(sent_at) >= 16 else sent_at

            content = msg.get('content', '')
            msg_type = msg.get('msg_type', '1')
            if msg_type == '3' or msg_type == 3:
                content = '[语音消息]'
            elif msg_type == '2' or msg_type == 2:
                content = '[图片]'
            elif msg_type == '49' or msg_type == 49:
                content = '[链接/小程序]'
            elif not content:
                content = f'[{msg_type}类型消息]'

            conversation_lines.append(f"[{role} {time_str}] {content}")

        conversation = '\n'.join(conversation_lines)

        # 获取add_time（从contacts表）
        add_time_str = '未知'
        try:
            ct_result = supabase.table('contacts').select('add_time').eq(
                'wechat_id', wechat_id
            ).eq('sales_wechat_id', sales_wechat_id).limit(1).execute()
            if ct_result.data and ct_result.data[0].get('add_time'):
                add_time_str = ct_result.data[0]['add_time']
        except Exception:
            pass

        input_data.append({
            'wechat_id': wechat_id,
            'sales_wechat_id': sales_wechat_id,
            'remark': c.get('remark') or c.get('nickname', ''),
            'sales_name': TEST_SALES.get(sales_wechat_id, ''),
            'stratum': c.get('stratum', ''),
            'msg_count': c.get('msg_count', 0),
            'has_quote': c.get('has_quote', False),
            'add_time': add_time_str,
            'conversation': conversation,
            'actual_msg_fetched': len(messages),
        })

    ensure_results_dir()
    with open(INPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(input_data, f, ensure_ascii=False, indent=2)
    logger.info(f"输入数据保存到: {INPUT_FILE}")
    return input_data


# ========================================================================
# Step 3: 调用模型API
# ========================================================================
def call_deepseek(prompt_text):
    """调用DeepSeek V3.2 (reasoner) — OpenAI兼容格式"""
    import openai
    client = openai.OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url='https://api.deepseek.com'
    )
    start = time.time()
    response = client.chat.completions.create(
        model='deepseek-reasoner',
        messages=[{'role': 'user', 'content': prompt_text}],
        temperature=0.1,
    )
    elapsed = time.time() - start
    choice = response.choices[0]
    content = choice.message.content or ''
    usage = response.usage
    return {
        'content': content,
        'input_tokens': usage.prompt_tokens if usage else 0,
        'output_tokens': usage.completion_tokens if usage else 0,
        'elapsed': round(elapsed, 2),
    }


def call_anthropic(model_id, prompt_text):
    """调用Anthropic模型（Haiku/Sonnet）— 原生SDK"""
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    start = time.time()
    response = client.messages.create(
        model=model_id,
        max_tokens=1024,
        messages=[{'role': 'user', 'content': prompt_text}],
    )
    elapsed = time.time() - start
    content = ''
    if response.content:
        for block in response.content:
            if hasattr(block, 'text'):
                content += block.text
    return {
        'content': content,
        'input_tokens': response.usage.input_tokens if response.usage else 0,
        'output_tokens': response.usage.output_tokens if response.usage else 0,
        'elapsed': round(elapsed, 2),
    }


def parse_json_response(text):
    """从模型输出中提取JSON"""
    text = text.strip()
    # 去掉markdown代码块
    if text.startswith('```'):
        lines = text.split('\n')
        lines = [l for l in lines if not l.strip().startswith('```')]
        text = '\n'.join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 尝试找到第一个{和最后一个}
        start = text.find('{')
        end = text.rfind('}')
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end+1])
            except json.JSONDecodeError:
                pass
    return None


def run_model(model_key, input_data):
    """对所有客户跑指定模型的诊断"""
    model_cfg = MODELS[model_key]
    logger.info(f"\n{'='*60}")
    logger.info(f"开始运行: {model_cfg['name']} ({len(input_data)}个客户)")
    logger.info(f"{'='*60}")

    # 检查API key
    if model_key == 'deepseek':
        if not DEEPSEEK_API_KEY:
            logger.error("DEEPSEEK_API_KEY 未设置，跳过DeepSeek")
            return None
    else:
        if not ANTHROPIC_API_KEY:
            logger.error("ANTHROPIC_API_KEY 未设置，跳过Anthropic模型")
            return None

    results = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_time = 0
    errors = 0

    for i, customer in enumerate(input_data):
        display_name = customer.get('remark') or customer.get('wechat_id', '')[:12]
        logger.info(f"  [{i+1}/{len(input_data)}] {display_name} ({customer.get('stratum','')})")

        # 构建prompt
        prompt_text = DIAGNOSIS_PROMPT.format(
            remark=customer.get('remark', '未知'),
            add_time=customer.get('add_time', '未知'),
            msg_count=customer.get('msg_count', 0),
            has_quote='是' if customer.get('has_quote') else '否',
            conversation=customer.get('conversation', '(无聊天记录)'),
        )

        try:
            if model_key == 'deepseek':
                resp = call_deepseek(prompt_text)
            else:
                resp = call_anthropic(model_cfg['model_id'], prompt_text)

            parsed = parse_json_response(resp['content'])
            if parsed is None:
                logger.warning(f"    JSON解析失败，原始输出: {resp['content'][:200]}")
                errors += 1

            results.append({
                'wechat_id': customer['wechat_id'],
                'sales_wechat_id': customer['sales_wechat_id'],
                'remark': customer.get('remark', ''),
                'stratum': customer.get('stratum', ''),
                'raw_output': resp['content'],
                'parsed': parsed,
                'input_tokens': resp['input_tokens'],
                'output_tokens': resp['output_tokens'],
                'elapsed': resp['elapsed'],
            })
            total_input_tokens += resp['input_tokens']
            total_output_tokens += resp['output_tokens']
            total_time += resp['elapsed']

            stage = parsed.get('stage', '?') if parsed else '解析失败'
            prob = parsed.get('purchase_probability', '?') if parsed else '?'
            logger.info(f"    → {stage} | 成交概率={prob} | "
                       f"tokens={resp['input_tokens']}+{resp['output_tokens']} | "
                       f"{resp['elapsed']}s")

        except Exception as e:
            logger.error(f"    API调用失败: {e}")
            errors += 1
            results.append({
                'wechat_id': customer['wechat_id'],
                'sales_wechat_id': customer['sales_wechat_id'],
                'remark': customer.get('remark', ''),
                'stratum': customer.get('stratum', ''),
                'raw_output': f'ERROR: {e}',
                'parsed': None,
                'input_tokens': 0,
                'output_tokens': 0,
                'elapsed': 0,
            })

        # 调用间隔
        time.sleep(1)

    # 计算费用
    cost_input = total_input_tokens / 1_000_000 * model_cfg['price_input']
    cost_output = total_output_tokens / 1_000_000 * model_cfg['price_output']
    cost_total_usd = cost_input + cost_output
    cost_total_cny = cost_total_usd * 7.2  # 粗略汇率

    summary = {
        'model': model_key,
        'model_name': model_cfg['name'],
        'total_customers': len(input_data),
        'total_input_tokens': total_input_tokens,
        'total_output_tokens': total_output_tokens,
        'total_time_seconds': round(total_time, 2),
        'cost_usd': round(cost_total_usd, 4),
        'cost_cny': round(cost_total_cny, 2),
        'errors': errors,
        'parse_failures': sum(1 for r in results if r['parsed'] is None),
    }
    logger.info(f"\n--- {model_cfg['name']} 汇总 ---")
    logger.info(f"  Input tokens: {total_input_tokens:,}")
    logger.info(f"  Output tokens: {total_output_tokens:,}")
    logger.info(f"  总耗时: {total_time:.1f}s")
    logger.info(f"  费用: ${cost_total_usd:.4f} (≈¥{cost_total_cny:.2f})")
    logger.info(f"  错误/解析失败: {errors}/{summary['parse_failures']}")

    # 保存结果
    result_file = os.path.join(RESULTS_DIR, f'results_{model_key}.json')
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump({'summary': summary, 'results': results}, f, ensure_ascii=False, indent=2)
    logger.info(f"  结果保存到: {result_file}")

    return {'summary': summary, 'results': results}


# ========================================================================
# Step 4: 生成对比报告
# ========================================================================
def generate_report():
    """生成Markdown对比报告"""
    logger.info("=== 生成对比报告 ===")

    # 加载各模型结果
    all_results = {}
    for model_key in ['deepseek', 'haiku', 'sonnet']:
        result_file = os.path.join(RESULTS_DIR, f'results_{model_key}.json')
        if os.path.exists(result_file):
            with open(result_file, 'r', encoding='utf-8') as f:
                all_results[model_key] = json.load(f)
        else:
            logger.warning(f"  {model_key} 结果文件不存在，跳过")

    if not all_results:
        logger.error("没有任何模型结果，无法生成报告")
        return

    # 加载输入数据
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        input_data = json.load(f)
    customer_map = {(c['wechat_id'], c['sales_wechat_id']): c for c in input_data}

    # ---- 报告内容 ----
    lines = []
    lines.append("# T-023: AI诊断A/B测试结果报告")
    lines.append(f"\n> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"> 测试客户数: {len(input_data)}")
    models_tested = list(all_results.keys())
    lines.append(f"> 测试模型: {', '.join(MODELS[m]['name'] for m in models_tested)}")

    # --- 1. 费用汇总 ---
    lines.append("\n## 1. 费用与性能汇总\n")
    lines.append("| 指标 | " + " | ".join(MODELS[m]['name'] for m in models_tested) + " |")
    lines.append("|---" + "|---" * len(models_tested) + "|")

    metrics = [
        ('Input Tokens', lambda s: f"{s['total_input_tokens']:,}"),
        ('Output Tokens', lambda s: f"{s['total_output_tokens']:,}"),
        ('总耗时(s)', lambda s: f"{s['total_time_seconds']:.1f}"),
        ('费用(USD)', lambda s: f"${s['cost_usd']:.4f}"),
        ('费用(CNY)', lambda s: f"¥{s['cost_cny']:.2f}"),
        ('解析失败数', lambda s: str(s['parse_failures'])),
        ('API错误数', lambda s: str(s['errors'])),
    ]
    for label, fn in metrics:
        row = f"| {label} |"
        for m in models_tested:
            summary = all_results[m]['summary']
            row += f" {fn(summary)} |"
        lines.append(row)

    # --- 2. 50客户对比表 ---
    lines.append("\n## 2. 50客户诊断对比\n")
    header = "| # | wechat_id | 备注名 | 销售 | 层级 | 条数 |"
    divider = "|---|---|---|---|---|---|"
    for m in models_tested:
        short = m.capitalize()
        header += f" {short}阶段 | {short}概率 | {short}建议 |"
        divider += "---|---|---|"
    lines.append(header)
    lines.append(divider)

    # 建立各模型结果索引
    model_idx = {}
    for m in models_tested:
        model_idx[m] = {}
        for r in all_results[m]['results']:
            key = (r['wechat_id'], r['sales_wechat_id'])
            model_idx[m][key] = r

    # 客户列表（按input_data顺序）
    for i, c in enumerate(input_data):
        key = (c['wechat_id'], c['sales_wechat_id'])
        wechat_id = c.get('wechat_id', '')
        remark = c.get('remark', '')
        row = f"| {i+1} | {wechat_id} | {remark} | {c.get('sales_name','')} | {c.get('stratum','')} | {c.get('msg_count',0)} |"
        for m in models_tested:
            r = model_idx[m].get(key, {})
            p = r.get('parsed') or {}
            stage = p.get('stage', '-')
            prob = p.get('purchase_probability', '-')
            suggestion = p.get('suggestion', '-')
            if len(suggestion) > 20:
                suggestion = suggestion[:18] + '..'
            row += f" {stage} | {prob} | {suggestion} |"
        lines.append(row)

    # --- 3. 阶段一致率 ---
    lines.append("\n## 3. 模型间阶段判断一致率\n")
    if len(models_tested) >= 2:
        pairs = []
        for i in range(len(models_tested)):
            for j in range(i+1, len(models_tested)):
                pairs.append((models_tested[i], models_tested[j]))

        lines.append("| 模型对 | 一致数 | 总数 | 一致率 |")
        lines.append("|---|---|---|---|")
        for m1, m2 in pairs:
            agree = 0
            total = 0
            for c in input_data:
                key = (c['wechat_id'], c['sales_wechat_id'])
                r1 = model_idx.get(m1, {}).get(key, {})
                r2 = model_idx.get(m2, {}).get(key, {})
                p1 = (r1.get('parsed') or {}).get('stage')
                p2 = (r2.get('parsed') or {}).get('stage')
                if p1 and p2:
                    total += 1
                    if p1 == p2:
                        agree += 1
            rate = f"{agree/total*100:.1f}%" if total > 0 else 'N/A'
            lines.append(f"| {MODELS[m1]['name']} vs {MODELS[m2]['name']} | {agree} | {total} | {rate} |")

    # --- 4. 抽样10个完整输出对比 ---
    lines.append("\n## 4. 抽样10客户完整输出对比\n")
    sample_indices = list(range(min(10, len(input_data))))
    # 从各层各选几个
    by_stratum = defaultdict(list)
    for i, c in enumerate(input_data):
        by_stratum[c.get('stratum', '')].append(i)
    sample_indices = []
    for stratum in ['deep', 'medium', 'shallow', 'quoted']:
        indices = by_stratum.get(stratum, [])
        sample_indices.extend(indices[:3 if stratum != 'quoted' else 1])
    sample_indices = sample_indices[:10]

    for idx in sample_indices:
        c = input_data[idx]
        key = (c['wechat_id'], c['sales_wechat_id'])
        wechat_id = c.get('wechat_id', '')
        remark = c.get('remark', '')
        lines.append(f"### 客户 {idx+1}: {wechat_id} ({remark}) ({c.get('stratum','')}, {c.get('msg_count',0)}条)")
        lines.append("")
        for m in models_tested:
            r = model_idx.get(m, {}).get(key, {})
            p = r.get('parsed')
            lines.append(f"**{MODELS[m]['name']}** (tokens: {r.get('input_tokens',0)}+{r.get('output_tokens',0)}, {r.get('elapsed',0)}s)")
            if p:
                lines.append(f"```json\n{json.dumps(p, ensure_ascii=False, indent=2)}\n```")
            else:
                raw = r.get('raw_output', '(无输出)')
                lines.append(f"```\n{raw[:500]}\n```")
            lines.append("")

    # --- 5. 结论 ---
    lines.append("\n## 5. 初步观察\n")
    lines.append("> 由人工审核后填写结论。以下为自动统计辅助信息：\n")

    # 各模型阶段分布
    for m in models_tested:
        stage_dist = defaultdict(int)
        for r in all_results[m]['results']:
            p = r.get('parsed') or {}
            stage = p.get('stage', '解析失败')
            stage_dist[stage] += 1
        sorted_stages = sorted(stage_dist.items(), key=lambda x: -x[1])
        lines.append(f"**{MODELS[m]['name']} 阶段分布**: " +
                     ", ".join(f"{s}({n})" for s, n in sorted_stages))

    # 写入报告
    report_dir = os.path.join(os.path.dirname(__file__), '..', 'docs', 'execution-reports')
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, 'T023-AB-test-results.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    logger.info(f"报告已生成: {report_path}")


# ========================================================================
# Main
# ========================================================================
def main():
    parser = argparse.ArgumentParser(description='T-023: AI诊断A/B测试')
    parser.add_argument('--select', action='store_true', help='分层抽样选客户')
    parser.add_argument('--run', action='store_true', help='执行模型诊断')
    parser.add_argument('--model', type=str, choices=['deepseek', 'haiku', 'sonnet'],
                        help='只跑指定模型（配合--run使用）')
    parser.add_argument('--report', action='store_true', help='生成对比报告')
    parser.add_argument('--all', action='store_true', help='执行全部流程')
    args = parser.parse_args()

    if not any([args.select, args.run, args.report, args.all]):
        parser.print_help()
        sys.exit(0)

    if args.all or args.select:
        customers = select_customers()
        input_data = prepare_input_data(customers)

    if args.all or args.run:
        # 加载输入数据
        if not os.path.exists(INPUT_FILE):
            logger.error("输入数据不存在，请先运行 --select")
            sys.exit(1)
        with open(INPUT_FILE, 'r', encoding='utf-8') as f:
            input_data = json.load(f)

        if args.model:
            models_to_run = [args.model]
        else:
            models_to_run = ['deepseek', 'haiku', 'sonnet']

        for model_key in models_to_run:
            run_model(model_key, input_data)

    if args.all or args.report:
        generate_report()


if __name__ == '__main__':
    main()
