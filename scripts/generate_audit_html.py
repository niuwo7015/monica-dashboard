#!/usr/bin/env python3
"""Generate HTML audit report for T-023 A/B test diagnosis results.

Combines chat records + 3 model diagnosis results into a single browsable HTML file.
"""

import json
import html
import os
import sys

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'ab_test')
OUTPUT_FILE = os.path.join(DATA_DIR, 'audit_report.html')


def load_json(filename):
    path = os.path.join(DATA_DIR, filename)
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def format_chat(conversation_text):
    """Format chat conversation into HTML with color-coded messages."""
    lines = []
    for line in conversation_text.strip().split('\n'):
        escaped = html.escape(line)
        if escaped.startswith('[客户'):
            lines.append(f'<div class="msg msg-customer">{escaped}</div>')
        elif escaped.startswith('[销售'):
            lines.append(f'<div class="msg msg-sales">{escaped}</div>')
        else:
            lines.append(f'<div class="msg">{escaped}</div>')
    return '\n'.join(lines)


def diagnosis_card(result, model_name, color):
    """Generate HTML card for one model's diagnosis."""
    if result is None:
        return f'''<div class="model-card" style="border-left: 4px solid {color}">
            <div class="model-name" style="color:{color}">{html.escape(model_name)}</div>
            <div class="no-data">该客户无诊断结果（不在此模型结果中）</div>
        </div>'''

    parsed = result.get('parsed')
    if parsed is None:
        raw = html.escape(result.get('raw_output', '(empty)'))
        return f'''<div class="model-card" style="border-left: 4px solid {color}">
            <div class="model-name" style="color:{color}">{html.escape(model_name)}</div>
            <div class="parse-fail">JSON解析失败</div>
            <details><summary>原始输出</summary><pre>{raw}</pre></details>
        </div>'''

    stage = html.escape(parsed.get('stage', '-'))
    prob = parsed.get('purchase_probability', '-')
    prob_escaped = html.escape(str(prob))
    signal = html.escape(parsed.get('key_signal', '-'))
    suggestion = html.escape(parsed.get('suggestion', '-'))
    risk = html.escape(parsed.get('risk', '-') or '无')

    prob_class = ''
    if prob in ('高', '高'):
        prob_class = 'prob-high'
    elif prob in ('中', '中'):
        prob_class = 'prob-mid'
    elif prob in ('低', '低'):
        prob_class = 'prob-low'

    return f'''<div class="model-card" style="border-left: 4px solid {color}">
        <div class="model-name" style="color:{color}">{html.escape(model_name)}</div>
        <table class="diagnosis-table">
            <tr><td class="label">阶段</td><td><strong>{stage}</strong></td></tr>
            <tr><td class="label">成交概率</td><td><span class="prob {prob_class}">{prob_escaped}</span></td></tr>
            <tr><td class="label">关键信号</td><td>{signal}</td></tr>
            <tr><td class="label">建议动作</td><td>{suggestion}</td></tr>
            <tr><td class="label">风险</td><td>{risk}</td></tr>
        </table>
    </div>'''


def generate_html(input_data, results_deepseek, results_haiku, results_sonnet):
    """Generate the full HTML report."""

    # Build lookup dicts by wechat_id
    def build_lookup(results_data):
        lookup = {}
        for r in results_data.get('results', []):
            lookup[r['wechat_id']] = r
        return lookup

    ds_lookup = build_lookup(results_deepseek)
    hk_lookup = build_lookup(results_haiku)
    sn_lookup = build_lookup(results_sonnet)

    customer_sections = []
    for idx, customer in enumerate(input_data):
        wechat_id = customer.get('wechat_id', '')
        remark = html.escape(customer.get('remark', ''))
        sales_name = html.escape(customer.get('sales_name', ''))
        stratum = html.escape(customer.get('stratum', ''))
        msg_count = customer.get('msg_count', 0)
        has_quote = customer.get('has_quote', False)
        conversation = customer.get('conversation', '')

        # Get results
        ds_result = ds_lookup.get(wechat_id)
        hk_result = hk_lookup.get(wechat_id)
        sn_result = sn_lookup.get(wechat_id)

        # Check agreement
        stages = []
        for r in [ds_result, hk_result, sn_result]:
            if r and r.get('parsed'):
                stages.append(r['parsed'].get('stage', ''))
        all_agree = len(set(stages)) == 1 and len(stages) == 3
        agree_badge = '<span class="badge badge-agree">三模型一致</span>' if all_agree else ''
        if len(set(stages)) == 3 and len(stages) == 3:
            agree_badge = '<span class="badge badge-disagree">三模型分歧</span>'

        chat_html = format_chat(conversation)
        quote_badge = '<span class="badge badge-quote">已报价</span>' if has_quote else ''

        section = f'''
        <div class="customer-section" id="customer-{idx+1}">
            <div class="customer-header" onclick="toggleCustomer({idx+1})">
                <span class="customer-num">#{idx+1}</span>
                <span class="customer-id">{html.escape(wechat_id)}</span>
                <span class="customer-remark">({remark})</span>
                <span class="customer-meta">{sales_name} | {stratum} | {msg_count}条</span>
                {quote_badge}
                {agree_badge}
                <span class="toggle-icon" id="icon-{idx+1}">▶</span>
            </div>
            <div class="customer-body" id="body-{idx+1}" style="display:none">
                <div class="section-row">
                    <div class="chat-section">
                        <h3>聊天记录 ({msg_count}条)</h3>
                        <div class="chat-box">
                            {chat_html}
                        </div>
                    </div>
                    <div class="diagnosis-section">
                        <h3>三模型诊断对比</h3>
                        {diagnosis_card(ds_result, 'DeepSeek V3.2 (reasoner)', '#1a73e8')}
                        {diagnosis_card(hk_result, 'Claude Haiku 4.5', '#34a853')}
                        {diagnosis_card(sn_result, 'Claude Sonnet 4.6', '#ea4335')}
                    </div>
                </div>
            </div>
        </div>'''
        customer_sections.append(section)

    sections_html = '\n'.join(customer_sections)

    # Summary stats
    ds_summary = results_deepseek.get('summary', {})
    hk_summary = results_haiku.get('summary', {})
    sn_summary = results_sonnet.get('summary', {})

    full_html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>T-023 AI诊断A/B测试 — 审计报告</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f5f5; color: #333; line-height: 1.6; }}
        .container {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}

        h1 {{ text-align: center; margin: 20px 0; color: #1a1a1a; }}
        .subtitle {{ text-align: center; color: #666; margin-bottom: 30px; }}

        /* Summary table */
        .summary-table {{ width: 100%; border-collapse: collapse; margin-bottom: 30px; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .summary-table th {{ background: #f0f0f0; padding: 10px 16px; text-align: left; font-weight: 600; border-bottom: 2px solid #ddd; }}
        .summary-table td {{ padding: 10px 16px; border-bottom: 1px solid #eee; }}
        .summary-table tr:hover {{ background: #fafafa; }}

        /* Controls */
        .controls {{ margin-bottom: 20px; display: flex; gap: 10px; flex-wrap: wrap; }}
        .controls button {{ padding: 8px 16px; border: 1px solid #ddd; border-radius: 6px; background: white; cursor: pointer; font-size: 14px; }}
        .controls button:hover {{ background: #e8e8e8; }}
        .controls .filter-label {{ line-height: 36px; font-weight: 500; }}

        /* Customer section */
        .customer-section {{ background: white; margin-bottom: 8px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); overflow: hidden; }}
        .customer-header {{ padding: 14px 20px; cursor: pointer; display: flex; align-items: center; gap: 12px; transition: background 0.2s; }}
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

        .customer-body {{ padding: 0 20px 20px; }}
        .section-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
        @media (max-width: 900px) {{ .section-row {{ grid-template-columns: 1fr; }} }}

        .chat-section h3, .diagnosis-section h3 {{ margin-bottom: 12px; color: #444; font-size: 15px; }}
        .chat-box {{ max-height: 500px; overflow-y: auto; padding: 12px; background: #f9f9f9; border-radius: 6px; border: 1px solid #eee; }}
        .msg {{ padding: 4px 0; font-size: 13px; word-break: break-all; }}
        .msg-customer {{ color: #1a73e8; }}
        .msg-sales {{ color: #34a853; }}

        /* Model cards */
        .model-card {{ padding: 12px 16px; margin-bottom: 10px; background: #fafafa; border-radius: 6px; }}
        .model-name {{ font-weight: 700; font-size: 14px; margin-bottom: 8px; }}
        .diagnosis-table {{ width: 100%; font-size: 13px; }}
        .diagnosis-table td {{ padding: 4px 8px; vertical-align: top; }}
        .diagnosis-table .label {{ color: #888; white-space: nowrap; width: 70px; font-weight: 500; }}
        .parse-fail {{ color: #dc3545; font-weight: 600; }}
        .no-data {{ color: #999; font-style: italic; }}

        .prob {{ padding: 2px 8px; border-radius: 4px; font-weight: 600; }}
        .prob-high {{ background: #d4edda; color: #155724; }}
        .prob-mid {{ background: #fff3cd; color: #856404; }}
        .prob-low {{ background: #f8d7da; color: #721c24; }}

        details summary {{ cursor: pointer; color: #666; font-size: 12px; }}
        details pre {{ font-size: 11px; white-space: pre-wrap; margin-top: 8px; background: #f0f0f0; padding: 8px; border-radius: 4px; }}

        /* Audit checkbox */
        .audit-row {{ margin-top: 12px; padding: 10px; background: #f0f7ff; border-radius: 6px; display: flex; gap: 12px; align-items: center; }}
        .audit-row label {{ font-weight: 500; font-size: 13px; }}
        .audit-row select {{ padding: 4px 8px; border-radius: 4px; border: 1px solid #ccc; }}
        .audit-row textarea {{ flex: 1; padding: 6px; border-radius: 4px; border: 1px solid #ccc; font-size: 13px; resize: vertical; min-height: 30px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>T-023 AI诊断A/B测试 — 审计报告</h1>
        <p class="subtitle">50个客户 × 3个模型 | 生成时间: 2026-03-12</p>

        <table class="summary-table">
            <thead>
                <tr>
                    <th>模型</th>
                    <th>完成数</th>
                    <th>费用(CNY)</th>
                    <th>耗时</th>
                    <th>均耗时/客户</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td><strong style="color:#1a73e8">DeepSeek V3.2 (reasoner)</strong></td>
                    <td>{ds_summary.get('total_customers', 50) - ds_summary.get('parse_failures', 0)}/50</td>
                    <td>¥{ds_summary.get('cost_cny', 0)}</td>
                    <td>{ds_summary.get('total_time_seconds', 0):.0f}s</td>
                    <td>{ds_summary.get('total_time_seconds', 0) / max(ds_summary.get('total_customers', 1), 1):.1f}s</td>
                </tr>
                <tr>
                    <td><strong style="color:#34a853">Claude Haiku 4.5</strong></td>
                    <td>{hk_summary.get('total_customers', 50) - hk_summary.get('parse_failures', 0)}/50</td>
                    <td>¥{hk_summary.get('cost_cny', 0)}</td>
                    <td>{hk_summary.get('total_time_seconds', 0):.0f}s</td>
                    <td>{hk_summary.get('total_time_seconds', 0) / max(hk_summary.get('total_customers', 1), 1):.1f}s</td>
                </tr>
                <tr>
                    <td><strong style="color:#ea4335">Claude Sonnet 4.6</strong></td>
                    <td>{sn_summary.get('total_customers', 50) - sn_summary.get('parse_failures', 0)}/50</td>
                    <td>¥{sn_summary.get('cost_cny', 0)}</td>
                    <td>{sn_summary.get('total_time_seconds', 0):.0f}s</td>
                    <td>{sn_summary.get('total_time_seconds', 0) / max(sn_summary.get('total_customers', 1), 1):.1f}s</td>
                </tr>
            </tbody>
        </table>

        <div class="controls">
            <span class="filter-label">筛选：</span>
            <button onclick="filterByStratum('all')">全部(50)</button>
            <button onclick="filterByStratum('deep')">深度(10)</button>
            <button onclick="filterByStratum('medium')">中等(15)</button>
            <button onclick="filterByStratum('shallow')">浅度(15)</button>
            <button onclick="filterByStratum('quoted')">已报价(10)</button>
            <span style="margin-left:20px" class="filter-label">操作：</span>
            <button onclick="expandAll()">全部展开</button>
            <button onclick="collapseAll()">全部收起</button>
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
                if (el.closest('.customer-section').style.display !== 'none') {{
                    el.style.display = 'block';
                }}
            }});
            document.querySelectorAll('.toggle-icon').forEach(function(el) {{ el.classList.add('open'); }});
        }}

        function collapseAll() {{
            document.querySelectorAll('.customer-body').forEach(function(el) {{ el.style.display = 'none'; }});
            document.querySelectorAll('.toggle-icon').forEach(function(el) {{ el.classList.remove('open'); }});
        }}

        function filterByStratum(stratum) {{
            document.querySelectorAll('.customer-section').forEach(function(el) {{
                if (stratum === 'all') {{
                    el.style.display = 'block';
                }} else {{
                    var meta = el.querySelector('.customer-meta').textContent;
                    el.style.display = meta.includes(stratum) ? 'block' : 'none';
                }}
            }});
        }}
    </script>
</body>
</html>'''
    return full_html


def main():
    print("Loading data files...")
    input_data = load_json('input_data.json')
    results_deepseek = load_json('results_deepseek.json')
    results_haiku = load_json('results_haiku.json')
    results_sonnet = load_json('results_sonnet.json')

    print(f"Loaded {len(input_data)} customers")
    print(f"DeepSeek: {len(results_deepseek['results'])} results")
    print(f"Haiku: {len(results_haiku['results'])} results")
    print(f"Sonnet: {len(results_sonnet['results'])} results")

    print("Generating HTML audit report...")
    html_content = generate_html(input_data, results_deepseek, results_haiku, results_sonnet)

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write(html_content)

    file_size = os.path.getsize(OUTPUT_FILE)
    print(f"Done! Report saved to: {OUTPUT_FILE}")
    print(f"File size: {file_size / 1024:.1f} KB")


if __name__ == '__main__':
    main()
