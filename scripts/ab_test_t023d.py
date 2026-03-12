#!/usr/bin/env python3
"""
T-023d: 融合业务知识的prompt三模型回归测试

复用T-023的50个客户数据，排除3个已成交客户，
用融合业务知识库的新prompt对47个客户跑DeepSeek V3.2 / Haiku 4.5 / Sonnet 4.6对比。

用法：
  python ab_test_t023d.py --run         # 执行全部三模型诊断
  python ab_test_t023d.py --run --model deepseek   # 只跑DeepSeek
  python ab_test_t023d.py --report      # 从已有结果生成报告
  python ab_test_t023d.py --all         # run + report
"""

import os
import sys
import json
import time
import html as html_mod
import argparse
import logging
from datetime import datetime
from collections import defaultdict

# ============ 配置 ============
SUPABASE_URL = os.getenv('SUPABASE_URL', 'https://dieeejjzbhkpgxdhwlxf.supabase.co')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')

# ============ 日志 ============
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ============ 排除的已成交客户 ============
EXCLUDED_WECHAT_IDS = {
    'wxid_8kvjlyd9so9a12',     # #13 D-25.0717 小杰的客户
    'wxid_vbogrguw9xtn22',     # #45 D25.10.28罗璇定制35云锦3 可欣的客户
    'wxid_cf0hlovo4z1p21',     # #47 D25.5.16 黄逸婷 像素 可欣的客户
}

# ============ 销售配置 ============
TEST_SALES = {
    'wxid_p03xoj66oss112': '小杰',
    'wxid_am3kdib9tt3722': '可欣',
    'wxid_cbk7hkyyp11t12': '霄剑',
}

# ============ 模型配置 ============
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', '')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')

MODELS = {
    'deepseek': {
        'name': 'DeepSeek V3.2 (reasoner)',
        'model_id': 'deepseek-reasoner',
        'base_url': 'https://api.deepseek.com',
        'price_input': 0.28,
        'price_output': 0.42,
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

MODEL_COLORS = {
    'deepseek': '#1a73e8',
    'haiku': '#34a853',
    'sonnet': '#ea4335',
}

# ============ 新Prompt（融合业务知识） ============
DIAGNOSIS_PROMPT = """你是高端定制家具品牌"莫妮卡摩卡"的销售分析AI。
品牌背景：买入edra等欧洲原版沙发1:1拆解复刻，价格为正版1/10-1/20。主力产品：岩石沙发、像素沙发、花瓣沙发、模块沙发。客单价8000-30000元，集中在13000-20000元。客户主要从小红书种草后加微信。
请分析聊天记录，输出JSON（不要输出其他内容，不要用markdown包裹）：
{{
  "action": "rush|revive|nurture|drop",
  "reason": "核心依据（一句话，20字内）",
  "do_this": "具体下一步动作（一句话，30字内，销售直接能执行）",
  "risk": "流失风险信号（没有则为null，15字内）"
}}
=== action判断规则（按优先级从高到低） ===
【最高优先级 → rush】以下任一出现即判rush，覆盖所有其他规则：
- 客户发送了CAD图/户型图/精确尺寸
- 客户主动询问价格、定金、付款方式
- 客户确认了面料/颜色/尺寸
- 客户问展厅地址或预约到访
- 客户说出装修节点（"月底进场""年前搬""下周开荒"）
- 客户收到面料小样后在5天内
- 以上信号出现后，不管之后沉默多久，只要客户没有明确拒绝，都是rush
  例：客户3月8日问"定金要多少"，之后沉默4天 → 仍然rush
【次优先级 → drop】明确拒绝或不可挽回：
- 客户说"已经买了/订好了/找别家了"且聊天中无本品牌付款记录 → drop
- 预算明确低于报价50%以上（如报价16000客户说预算四位数）→ drop
- 客户已被删好友/拉黑 → drop
- 价差超过35%且客户已付款给竞品 → drop
【第三优先级 → revive】沉默但有价值：
- 报价后超过48小时无回应（这是60%流失发生的节点）→ revive，且risk标注"报价后沉默"
- 寄样后超过5天无反馈 → revive，且risk标注"寄样后沉默"
- 沉默>14天但有深度互动历史（≥15条或has_quote=true）→ revive
- 客户提到过竞品价格但没说已购买 → revive
【最低优先级 → nurture】时机未到：
- 浅度接触（<10条消息）且无明确需求
- 装修早期（刚交房/水电阶段）
- 客户说"有需要再联系"且无其他推进信号
- 沉默>14天且历史互动<10条
=== do_this生成规则 ===
- 必须具体到产品名/面料/场景，禁止写"保持跟进""发送优惠"等空话
- rush客户：动作围绕推进下一步（出方案/报价/寄样/收定金）
- revive客户（报价后沉默）：不要重复催单，带新价值（出库案例图/竞品对比/活动截止提醒）
- revive客户（寄样后沉默）：主动问"小样到了吗/感觉怎么样"，准备替代面料方案
- 如果客户提到竞品：do_this应包含成本拆解（松木vs橡胶木/海绵配比/原版拆解背书）
- 如果客户说"让家人商量"：do_this应为"提出拉群，把决策人纳入沟通"
- 如果客户在装修早期且沉默：do_this应为低频维护，等装修节点
=== risk标注规则 ===
- 报价后>48小时无回应 → "报价后沉默，高危流失节点"
- 寄样后>5天无反馈 → "寄样后沉默"
- 客户提到竞品具体价格 → "竞品比价中"
- 客户说"让老公/家人商量" → "决策人缺席"
- 设计师被提及 → "设计师可能截胡"
- 连续催单>2次无回应 → "过度催单风险"
- 价差在1000-3000元区间 → "危险价差区间"

客户信息：
- 备注名：{remark}
- 加微时间：{add_time}
- 聊天总条数：{msg_count}
- 是否报过价：{has_quote}

聊天记录（最近50条，从旧到新）：
{conversation}"""

# ============ 文件路径 ============
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, '..', 'data', 'ab_test')
T023D_DIR = os.path.join(SCRIPT_DIR, '..', 'data', 'ab_test_t023d')
INPUT_FILE_T023 = os.path.join(DATA_DIR, 'input_data.json')
INPUT_FILE = os.path.join(T023D_DIR, 'input_data_47.json')
REPORT_DIR = os.path.join(SCRIPT_DIR, '..', 'docs', 'execution-reports')


def ensure_dirs():
    os.makedirs(T023D_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)


# ========================================================================
# Step 1: 准备47个客户数据（从T-023的50个中排除3个）
# ========================================================================
def prepare_input_data():
    """从T-023的input_data.json中排除3个已成交客户"""
    if os.path.exists(INPUT_FILE):
        logger.info(f"已有47客户数据文件: {INPUT_FILE}")
        with open(INPUT_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        logger.info(f"加载了 {len(data)} 个客户")
        return data

    if not os.path.exists(INPUT_FILE_T023):
        logger.error(f"T-023输入数据文件不存在: {INPUT_FILE_T023}")
        logger.error("请确保 data/ab_test/input_data.json 存在（从T-023运行产生）")
        sys.exit(1)

    with open(INPUT_FILE_T023, 'r', encoding='utf-8') as f:
        all_customers = json.load(f)
    logger.info(f"从T-023加载 {len(all_customers)} 个客户")

    # 排除3个已成交客户
    filtered = [c for c in all_customers if c['wechat_id'] not in EXCLUDED_WECHAT_IDS]
    excluded_count = len(all_customers) - len(filtered)
    logger.info(f"排除 {excluded_count} 个已成交客户，剩余 {len(filtered)} 个")

    # 打印被排除的客户
    for c in all_customers:
        if c['wechat_id'] in EXCLUDED_WECHAT_IDS:
            logger.info(f"  排除: {c.get('remark', '')} ({c['wechat_id']})")

    ensure_dirs()
    with open(INPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(filtered, f, ensure_ascii=False, indent=2)
    logger.info(f"47客户数据保存到: {INPUT_FILE}")
    return filtered


# ========================================================================
# Step 2: API调用
# ========================================================================
def call_deepseek(prompt_text):
    import openai
    client = openai.OpenAI(api_key=DEEPSEEK_API_KEY, base_url='https://api.deepseek.com')
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
    text = text.strip()
    if text.startswith('```'):
        lines = text.split('\n')
        lines = [l for l in lines if not l.strip().startswith('```')]
        text = '\n'.join(lines).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find('{')
        end = text.rfind('}')
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end+1])
            except json.JSONDecodeError:
                pass
    return None


def run_model(model_key, input_data):
    model_cfg = MODELS[model_key]
    logger.info(f"\n{'='*60}")
    logger.info(f"开始运行: {model_cfg['name']} ({len(input_data)}个客户)")
    logger.info(f"{'='*60}")

    if model_key == 'deepseek':
        if not DEEPSEEK_API_KEY:
            logger.error("DEEPSEEK_API_KEY 未设置")
            return None
    else:
        if not ANTHROPIC_API_KEY:
            logger.error("ANTHROPIC_API_KEY 未设置")
            return None

    results = []
    total_input_tokens = 0
    total_output_tokens = 0
    total_time = 0
    errors = 0

    for i, customer in enumerate(input_data):
        display_name = customer.get('remark') or customer.get('wechat_id', '')[:12]
        logger.info(f"  [{i+1}/{len(input_data)}] {display_name}")

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
                logger.warning(f"    JSON解析失败: {resp['content'][:200]}")
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

            action = parsed.get('action', '?') if parsed else '解析失败'
            reason = parsed.get('reason', '?') if parsed else '?'
            logger.info(f"    → {action} | {reason} | "
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

        time.sleep(1)

    cost_input = total_input_tokens / 1_000_000 * model_cfg['price_input']
    cost_output = total_output_tokens / 1_000_000 * model_cfg['price_output']
    cost_total_usd = cost_input + cost_output
    cost_total_cny = cost_total_usd * 7.2

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

    result_file = os.path.join(T023D_DIR, f'results_{model_key}.json')
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump({'summary': summary, 'results': results}, f, ensure_ascii=False, indent=2)
    logger.info(f"  结果保存到: {result_file}")
    return {'summary': summary, 'results': results}


# ========================================================================
# Step 3: 生成报告
# ========================================================================
def format_chat_html(conversation_text):
    lines = []
    for line in conversation_text.strip().split('\n'):
        escaped = html_mod.escape(line)
        if escaped.startswith('[客户'):
            lines.append(f'<div class="msg msg-customer">{escaped}</div>')
        elif escaped.startswith('[销售'):
            lines.append(f'<div class="msg msg-sales">{escaped}</div>')
        else:
            lines.append(f'<div class="msg">{escaped}</div>')
    return '\n'.join(lines)


def diagnosis_card_html(result, model_name, color):
    if result is None:
        return f'''<div class="model-card" style="border-left: 4px solid {color}">
            <div class="model-name" style="color:{color}">{html_mod.escape(model_name)}</div>
            <div class="no-data">无诊断结果</div>
        </div>'''

    parsed = result.get('parsed')
    if parsed is None:
        raw = html_mod.escape(result.get('raw_output', '(empty)'))
        return f'''<div class="model-card" style="border-left: 4px solid {color}">
            <div class="model-name" style="color:{color}">{html_mod.escape(model_name)}</div>
            <div class="parse-fail">JSON解析失败</div>
            <details><summary>原始输出</summary><pre>{raw}</pre></details>
        </div>'''

    action = html_mod.escape(parsed.get('action', '-'))
    reason = html_mod.escape(parsed.get('reason', '-'))
    do_this = html_mod.escape(parsed.get('do_this', '-'))
    risk = html_mod.escape(str(parsed.get('risk') or '无'))

    action_colors = {
        'rush': '#d4edda',
        'revive': '#fff3cd',
        'nurture': '#d1ecf1',
        'drop': '#f8d7da',
    }
    action_bg = action_colors.get(parsed.get('action', ''), '#f0f0f0')

    tokens_info = f"{result.get('input_tokens', 0)}+{result.get('output_tokens', 0)} tokens, {result.get('elapsed', 0)}s"

    return f'''<div class="model-card" style="border-left: 4px solid {color}">
        <div class="model-name" style="color:{color}">{html_mod.escape(model_name)} <span class="tokens-info">({tokens_info})</span></div>
        <table class="diagnosis-table">
            <tr><td class="label">Action</td><td><span class="action-badge" style="background:{action_bg}"><strong>{action}</strong></span></td></tr>
            <tr><td class="label">原因</td><td>{reason}</td></tr>
            <tr><td class="label">下一步</td><td>{do_this}</td></tr>
            <tr><td class="label">风险</td><td>{risk}</td></tr>
        </table>
    </div>'''


def generate_html_report(input_data, all_results):
    """Generate HTML audit report."""
    models_tested = [m for m in ['deepseek', 'haiku', 'sonnet'] if m in all_results]
    total_customers = len(input_data)

    # Build lookups
    model_lookups = {}
    for m in models_tested:
        lookup = {}
        for r in all_results[m].get('results', []):
            lookup[r['wechat_id']] = r
        model_lookups[m] = lookup

    # Action distribution per model
    action_dists = {}
    for m in models_tested:
        dist = defaultdict(int)
        for r in all_results[m]['results']:
            p = r.get('parsed') or {}
            dist[p.get('action', '解析失败')] += 1
        action_dists[m] = dict(dist)

    # Agreement stats
    agree_count = 0
    disagree_customers = []
    for c in input_data:
        wid = c['wechat_id']
        actions = []
        for m in models_tested:
            r = model_lookups[m].get(wid)
            if r and r.get('parsed'):
                actions.append(r['parsed'].get('action', ''))
        if len(actions) == len(models_tested):
            if len(set(actions)) == 1:
                agree_count += 1
            else:
                disagree_customers.append((c, actions))

    valid_count = sum(1 for c in input_data
                      if all(model_lookups[m].get(c['wechat_id'], {}).get('parsed') for m in models_tested))
    agree_rate = f"{agree_count/valid_count*100:.1f}%" if valid_count > 0 else 'N/A'

    # Customer sections
    customer_sections = []
    for idx, customer in enumerate(input_data):
        wechat_id = customer.get('wechat_id', '')
        remark = html_mod.escape(customer.get('remark', ''))
        sales_name = html_mod.escape(customer.get('sales_name', ''))
        stratum = customer.get('stratum', '')
        msg_count = customer.get('msg_count', 0)
        has_quote = customer.get('has_quote', False)
        conversation = customer.get('conversation', '')

        results_for_customer = {}
        actions = []
        for m in models_tested:
            r = model_lookups[m].get(wechat_id)
            results_for_customer[m] = r
            if r and r.get('parsed'):
                actions.append(r['parsed'].get('action', ''))

        all_agree = len(set(actions)) == 1 and len(actions) == len(models_tested)
        all_disagree = len(set(actions)) == len(models_tested) and len(actions) == len(models_tested)
        any_parse_fail = any(
            (results_for_customer.get(m) and results_for_customer[m].get('parsed') is None)
            for m in models_tested
        )

        badges = []
        if has_quote:
            badges.append('<span class="badge badge-quote">已报价</span>')
        if all_agree:
            badges.append('<span class="badge badge-agree">三模型一致</span>')
        elif all_disagree:
            badges.append('<span class="badge badge-disagree">三模型分歧</span>')
        if any_parse_fail:
            badges.append('<span class="badge badge-parse-fail">解析失败</span>')
        badges_html = ' '.join(badges)

        chat_html = format_chat_html(conversation)

        cards_html = ''
        for m in models_tested:
            cards_html += diagnosis_card_html(results_for_customer[m], MODELS[m]['name'], MODEL_COLORS[m])

        section = f'''
        <div class="customer-section" data-stratum="{stratum}">
            <div class="customer-header" onclick="toggleCustomer({idx})">
                <span class="customer-num">#{idx+1}</span>
                <span class="customer-id">{html_mod.escape(wechat_id)}</span>
                <span class="customer-remark">({remark})</span>
                <span class="customer-meta">{sales_name} | {stratum} | {msg_count}条</span>
                {badges_html}
                <span class="toggle-icon" id="icon-{idx}">▶</span>
            </div>
            <div class="customer-body" id="body-{idx}" style="display:none">
                <div class="section-row">
                    <div class="chat-section">
                        <h3>聊天记录 ({msg_count}条)</h3>
                        <div class="chat-box">{chat_html}</div>
                    </div>
                    <div class="diagnosis-section">
                        <h3>三模型诊断对比</h3>
                        {cards_html}
                    </div>
                </div>
            </div>
        </div>'''
        customer_sections.append(section)

    sections_html = '\n'.join(customer_sections)

    # Summary rows
    summary_rows = ''
    for m in models_tested:
        s = all_results[m].get('summary', {})
        color = MODEL_COLORS[m]
        summary_rows += f'''<tr>
            <td><strong style="color:{color}">{html_mod.escape(MODELS[m]['name'])}</strong></td>
            <td>{s.get('total_customers', 0) - s.get('parse_failures', 0)}/{s.get('total_customers', 0)}</td>
            <td>¥{s.get('cost_cny', 0):.2f}</td>
            <td>{s.get('total_time_seconds', 0):.0f}s</td>
            <td>{s.get('total_time_seconds', 0) / max(s.get('total_customers', 1), 1):.1f}s</td>
            <td>{s.get('parse_failures', 0)}</td>
        </tr>'''

    # Action distribution table
    all_actions = sorted(set(a for d in action_dists.values() for a in d))
    action_header = '<th>Action</th>' + ''.join(f'<th>{MODELS[m]["name"]}</th>' for m in models_tested)
    action_rows = ''
    for action in all_actions:
        action_rows += f'<tr><td><strong>{html_mod.escape(action)}</strong></td>'
        for m in models_tested:
            count = action_dists[m].get(action, 0)
            action_rows += f'<td>{count}</td>'
        action_rows += '</tr>'

    # Pairwise agreement
    pair_rows = ''
    for i in range(len(models_tested)):
        for j in range(i+1, len(models_tested)):
            m1, m2 = models_tested[i], models_tested[j]
            agree = 0
            total = 0
            for c in input_data:
                wid = c['wechat_id']
                r1 = model_lookups[m1].get(wid, {})
                r2 = model_lookups[m2].get(wid, {})
                p1 = (r1.get('parsed') or {}).get('action')
                p2 = (r2.get('parsed') or {}).get('action')
                if p1 and p2:
                    total += 1
                    if p1 == p2:
                        agree += 1
            rate = f"{agree/total*100:.1f}%" if total > 0 else 'N/A'
            pair_rows += f'<tr><td>{MODELS[m1]["name"]} vs {MODELS[m2]["name"]}</td><td>{agree}</td><td>{total}</td><td><strong>{rate}</strong></td></tr>'

    # Stratum counts for filter buttons
    stratum_counts = defaultdict(int)
    for c in input_data:
        stratum_counts[c.get('stratum', 'unknown')] += 1

    filter_buttons = f'<button onclick="filterByStratum(\'all\')">全部({total_customers})</button>'
    for s in ['deep', 'medium', 'shallow', 'quoted']:
        if s in stratum_counts:
            filter_buttons += f'<button onclick="filterByStratum(\'{s}\')">{s}({stratum_counts[s]})</button>'

    full_html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>T-023d AI诊断回归测试 — 审计报告</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f5f5; color: #333; line-height: 1.6; }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
        h1 {{ text-align: center; margin: 20px 0; color: #1a1a1a; }}
        h2 {{ margin: 24px 0 12px; color: #333; border-bottom: 2px solid #ddd; padding-bottom: 6px; }}
        .subtitle {{ text-align: center; color: #666; margin-bottom: 30px; }}

        .summary-table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .summary-table th {{ background: #f0f0f0; padding: 10px 16px; text-align: left; font-weight: 600; border-bottom: 2px solid #ddd; }}
        .summary-table td {{ padding: 10px 16px; border-bottom: 1px solid #eee; }}
        .summary-table tr:hover {{ background: #fafafa; }}

        .controls {{ margin-bottom: 20px; display: flex; gap: 10px; flex-wrap: wrap; }}
        .controls button {{ padding: 8px 16px; border: 1px solid #ddd; border-radius: 6px; background: white; cursor: pointer; font-size: 14px; }}
        .controls button:hover {{ background: #e8e8e8; }}
        .controls .filter-label {{ line-height: 36px; font-weight: 500; }}

        .customer-section {{ background: white; margin-bottom: 8px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); overflow: hidden; }}
        .customer-header {{ padding: 14px 20px; cursor: pointer; display: flex; align-items: center; gap: 12px; transition: background 0.2s; flex-wrap: wrap; }}
        .customer-header:hover {{ background: #f5f7fa; }}
        .customer-num {{ font-weight: 700; color: #666; min-width: 30px; }}
        .customer-id {{ font-family: monospace; font-size: 13px; color: #1a73e8; }}
        .customer-remark {{ color: #333; font-weight: 500; }}
        .customer-meta {{ color: #888; font-size: 13px; margin-left: auto; }}
        .toggle-icon {{ color: #999; font-size: 12px; transition: transform 0.2s; }}
        .toggle-icon.open {{ transform: rotate(90deg); }}

        .badge {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 500; }}
        .badge-quote {{ background: #fff3cd; color: #856404; }}
        .badge-agree {{ background: #d4edda; color: #155724; }}
        .badge-disagree {{ background: #f8d7da; color: #721c24; }}
        .badge-parse-fail {{ background: #e2e3e5; color: #383d41; }}

        .customer-body {{ padding: 0 20px 20px; }}
        .section-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
        @media (max-width: 900px) {{ .section-row {{ grid-template-columns: 1fr; }} }}

        .chat-section h3, .diagnosis-section h3 {{ margin-bottom: 12px; color: #444; font-size: 15px; }}
        .chat-box {{ max-height: 500px; overflow-y: auto; padding: 12px; background: #f9f9f9; border-radius: 6px; border: 1px solid #eee; }}
        .msg {{ padding: 4px 0; font-size: 13px; word-break: break-all; }}
        .msg-customer {{ color: #1a73e8; }}
        .msg-sales {{ color: #34a853; }}

        .model-card {{ padding: 12px 16px; margin-bottom: 10px; background: #fafafa; border-radius: 6px; }}
        .model-name {{ font-weight: 700; font-size: 14px; margin-bottom: 8px; }}
        .tokens-info {{ font-weight: 400; font-size: 11px; color: #888; }}
        .diagnosis-table {{ width: 100%; font-size: 13px; }}
        .diagnosis-table td {{ padding: 4px 8px; vertical-align: top; }}
        .diagnosis-table .label {{ color: #888; white-space: nowrap; width: 60px; font-weight: 500; }}
        .action-badge {{ padding: 2px 10px; border-radius: 4px; font-size: 13px; }}
        .parse-fail {{ color: #dc3545; font-weight: 600; }}
        .no-data {{ color: #999; font-style: italic; }}

        details summary {{ cursor: pointer; color: #666; font-size: 12px; }}
        details pre {{ font-size: 11px; white-space: pre-wrap; margin-top: 8px; background: #f0f0f0; padding: 8px; border-radius: 4px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>T-023d 融合业务知识prompt回归测试 — 审计报告</h1>
        <p class="subtitle">{total_customers}个客户 × {len(models_tested)}个模型 | 三模型一致率: {agree_rate} | 生成: {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>

        <h2>费用与性能</h2>
        <table class="summary-table">
            <thead>
                <tr><th>模型</th><th>成功/总数</th><th>费用(CNY)</th><th>耗时</th><th>均耗时/客户</th><th>解析失败</th></tr>
            </thead>
            <tbody>{summary_rows}</tbody>
        </table>

        <h2>Action分布</h2>
        <table class="summary-table">
            <thead><tr>{action_header}</tr></thead>
            <tbody>{action_rows}</tbody>
        </table>

        <h2>模型间一致率</h2>
        <table class="summary-table">
            <thead><tr><th>模型对</th><th>一致数</th><th>总数</th><th>一致率</th></tr></thead>
            <tbody>{pair_rows}</tbody>
        </table>

        <h2>逐客户审计</h2>
        <div class="controls">
            <span class="filter-label">筛选：</span>
            {filter_buttons}
            <span style="margin-left:20px" class="filter-label">操作：</span>
            <button onclick="expandAll()">全部展开</button>
            <button onclick="collapseAll()">全部收起</button>
            <button onclick="filterDisagree()">只看分歧</button>
            <button onclick="filterParseFail()">只看解析失败</button>
        </div>

        <div id="customer-list">
            {sections_html}
        </div>
    </div>

    <script>
        function toggleCustomer(idx) {{
            var body = document.getElementById('body-' + idx);
            var icon = document.getElementById('icon-' + idx);
            if (body.style.display === 'none') {{
                body.style.display = 'block';
                icon.classList.add('open');
            }} else {{
                body.style.display = 'none';
                icon.classList.remove('open');
            }}
        }}
        function expandAll() {{
            document.querySelectorAll('.customer-body').forEach(function(el) {{
                if (el.closest('.customer-section').style.display !== 'none') el.style.display = 'block';
            }});
            document.querySelectorAll('.toggle-icon').forEach(function(el) {{ el.classList.add('open'); }});
        }}
        function collapseAll() {{
            document.querySelectorAll('.customer-body').forEach(function(el) {{ el.style.display = 'none'; }});
            document.querySelectorAll('.toggle-icon').forEach(function(el) {{ el.classList.remove('open'); }});
        }}
        function filterByStratum(stratum) {{
            document.querySelectorAll('.customer-section').forEach(function(el) {{
                if (stratum === 'all') {{ el.style.display = 'block'; }}
                else {{ el.style.display = el.dataset.stratum === stratum ? 'block' : 'none'; }}
            }});
        }}
        function filterDisagree() {{
            document.querySelectorAll('.customer-section').forEach(function(el) {{
                el.style.display = el.querySelector('.badge-disagree') ? 'block' : 'none';
            }});
        }}
        function filterParseFail() {{
            document.querySelectorAll('.customer-section').forEach(function(el) {{
                el.style.display = el.querySelector('.badge-parse-fail') ? 'block' : 'none';
            }});
        }}
    </script>
</body>
</html>'''
    return full_html


def generate_markdown_report(input_data, all_results):
    """Generate markdown summary report."""
    models_tested = [m for m in ['deepseek', 'haiku', 'sonnet'] if m in all_results]
    lines = []
    lines.append("# T-023d: 融合业务知识prompt三模型回归测试结果")
    lines.append(f"\n> 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"> 测试客户数: {len(input_data)}（从T-023的50个中排除3个已成交）")
    lines.append(f"> 测试模型: {', '.join(MODELS[m]['name'] for m in models_tested)}")
    lines.append(f"> prompt: 融合业务知识库版本（品牌背景+详细action规则+do_this规则+risk规则）")

    # Build lookups
    model_lookups = {}
    for m in models_tested:
        lookup = {}
        for r in all_results[m].get('results', []):
            lookup[r['wechat_id']] = r
        model_lookups[m] = lookup

    # 1. Cost summary
    lines.append("\n## 1. 费用与性能\n")
    lines.append("| 指标 | " + " | ".join(MODELS[m]['name'] for m in models_tested) + " |")
    lines.append("|---" + "|---" * len(models_tested) + "|")

    metrics = [
        ('Input Tokens', lambda s: f"{s['total_input_tokens']:,}"),
        ('Output Tokens', lambda s: f"{s['total_output_tokens']:,}"),
        ('总耗时(s)', lambda s: f"{s['total_time_seconds']:.1f}"),
        ('费用(USD)', lambda s: f"${s['cost_usd']:.4f}"),
        ('费用(CNY)', lambda s: f"¥{s['cost_cny']:.2f}"),
        ('解析失败', lambda s: str(s['parse_failures'])),
    ]
    for label, fn in metrics:
        row = f"| {label} |"
        for m in models_tested:
            row += f" {fn(all_results[m]['summary'])} |"
        lines.append(row)

    # 2. Action distribution
    lines.append("\n## 2. Action分布\n")
    for m in models_tested:
        dist = defaultdict(int)
        for r in all_results[m]['results']:
            p = r.get('parsed') or {}
            dist[p.get('action', '解析失败')] += 1
        sorted_actions = sorted(dist.items(), key=lambda x: -x[1])
        lines.append(f"**{MODELS[m]['name']}**: " + ", ".join(f"{a}({n})" for a, n in sorted_actions))

    # 3. Agreement
    lines.append("\n## 3. 模型间一致率\n")
    lines.append("| 模型对 | 一致数 | 总数 | 一致率 |")
    lines.append("|---|---|---|---|")
    for i in range(len(models_tested)):
        for j in range(i+1, len(models_tested)):
            m1, m2 = models_tested[i], models_tested[j]
            agree = 0
            total = 0
            for c in input_data:
                wid = c['wechat_id']
                r1 = model_lookups[m1].get(wid, {})
                r2 = model_lookups[m2].get(wid, {})
                p1 = (r1.get('parsed') or {}).get('action')
                p2 = (r2.get('parsed') or {}).get('action')
                if p1 and p2:
                    total += 1
                    if p1 == p2:
                        agree += 1
            rate = f"{agree/total*100:.1f}%" if total > 0 else 'N/A'
            lines.append(f"| {MODELS[m1]['name']} vs {MODELS[m2]['name']} | {agree} | {total} | {rate} |")

    # 4. Disagreements
    lines.append("\n## 4. 三模型分歧客户\n")
    lines.append("| # | wechat_id | 备注名 | 销售 | " + " | ".join(m.capitalize() for m in models_tested) + " |")
    lines.append("|---|---|---|---|" + "---|" * len(models_tested))
    disagree_count = 0
    for idx, c in enumerate(input_data):
        wid = c['wechat_id']
        actions = {}
        for m in models_tested:
            r = model_lookups[m].get(wid, {})
            p = (r.get('parsed') or {})
            actions[m] = p.get('action', '-')
        unique_actions = set(a for a in actions.values() if a != '-')
        if len(unique_actions) > 1:
            disagree_count += 1
            row = f"| {idx+1} | {wid} | {c.get('remark', '')} | {c.get('sales_name', '')} |"
            for m in models_tested:
                row += f" {actions[m]} |"
            lines.append(row)
    if disagree_count == 0:
        lines.append("*无分歧*")

    # 5. Parse failures
    lines.append("\n## 5. JSON解析失败客户\n")
    fail_count = 0
    for idx, c in enumerate(input_data):
        wid = c['wechat_id']
        failed_models = []
        for m in models_tested:
            r = model_lookups[m].get(wid, {})
            if r and r.get('parsed') is None:
                failed_models.append(m)
        if failed_models:
            fail_count += 1
            lines.append(f"- #{idx+1} {c.get('remark', '')} ({wid}): {', '.join(failed_models)}")
    if fail_count == 0:
        lines.append("*无解析失败*")

    # 6. Full comparison table
    lines.append("\n## 6. 47客户完整对比\n")
    header = "| # | 备注名 | 销售 | 层级 | 条数 |"
    divider = "|---|---|---|---|---|"
    for m in models_tested:
        short = m[:2].upper()
        header += f" {short} action | {short} do_this |"
        divider += "---|---|"
    lines.append(header)
    lines.append(divider)

    for idx, c in enumerate(input_data):
        wid = c['wechat_id']
        row = f"| {idx+1} | {c.get('remark', '')[:15]} | {c.get('sales_name', '')} | {c.get('stratum', '')} | {c.get('msg_count', 0)} |"
        for m in models_tested:
            r = model_lookups[m].get(wid, {})
            p = (r.get('parsed') or {})
            action = p.get('action', '-')
            do_this = p.get('do_this', '-')
            if len(do_this) > 20:
                do_this = do_this[:18] + '..'
            row += f" {action} | {do_this} |"
        lines.append(row)

    return '\n'.join(lines)


def generate_reports():
    """Load results and generate both HTML and markdown reports."""
    logger.info("=== 生成报告 ===")

    # Load input data
    if not os.path.exists(INPUT_FILE):
        logger.error(f"输入数据不存在: {INPUT_FILE}")
        sys.exit(1)
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        input_data = json.load(f)
    logger.info(f"加载 {len(input_data)} 个客户数据")

    # Load results
    all_results = {}
    for model_key in ['deepseek', 'haiku', 'sonnet']:
        result_file = os.path.join(T023D_DIR, f'results_{model_key}.json')
        if os.path.exists(result_file):
            with open(result_file, 'r', encoding='utf-8') as f:
                all_results[model_key] = json.load(f)
            logger.info(f"  加载 {model_key}: {len(all_results[model_key]['results'])} 结果")
        else:
            logger.warning(f"  {model_key} 结果不存在，跳过")

    if not all_results:
        logger.error("没有任何模型结果")
        return

    ensure_dirs()

    # HTML report
    html_path = os.path.join(REPORT_DIR, 'T023d-audit-report.html')
    html_content = generate_html_report(input_data, all_results)
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    html_size = os.path.getsize(html_path) / 1024
    logger.info(f"HTML报告: {html_path} ({html_size:.1f} KB)")

    # Markdown report
    md_path = os.path.join(REPORT_DIR, 'T023d-results.md')
    md_content = generate_markdown_report(input_data, all_results)
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md_content)
    logger.info(f"Markdown报告: {md_path}")


# ========================================================================
# Main
# ========================================================================
def main():
    parser = argparse.ArgumentParser(description='T-023d: 融合业务知识prompt回归测试')
    parser.add_argument('--run', action='store_true', help='执行模型诊断')
    parser.add_argument('--model', type=str, choices=['deepseek', 'haiku', 'sonnet'],
                        help='只跑指定模型')
    parser.add_argument('--report', action='store_true', help='生成报告')
    parser.add_argument('--all', action='store_true', help='run + report')
    args = parser.parse_args()

    if not any([args.run, args.report, args.all]):
        parser.print_help()
        sys.exit(0)

    if args.all or args.run:
        input_data = prepare_input_data()

        if args.model:
            models_to_run = [args.model]
        else:
            models_to_run = ['deepseek', 'haiku', 'sonnet']

        for model_key in models_to_run:
            run_model(model_key, input_data)

    if args.all or args.report:
        generate_reports()


if __name__ == '__main__':
    main()
