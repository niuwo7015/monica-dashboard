#!/usr/bin/env python3
"""T-023b: Regression test — 5 cases × 3 models with new 4-action prompt.

Reads existing input_data.json from T-023, runs 5 specific customers through
DeepSeek V3.2, Haiku 4.5, Sonnet 4.6 using the updated prompt, and generates
a markdown report.

Usage (local, with API keys in env):
    set DEEPSEEK_API_KEY=...
    set ANTHROPIC_API_KEY=...
    python scripts/regression_test_t023b.py
"""

import json
import os
import sys
import time
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

# Import prompt from main script
sys.path.insert(0, os.path.dirname(__file__))
from ab_test_diagnosis import (
    DIAGNOSIS_PROMPT, MODELS,
    call_deepseek, call_anthropic, parse_json_response,
)

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'ab_test')
REPORT_PATH = os.path.join(os.path.dirname(__file__), '..', 'docs', 'execution-reports', 'T023b-regression-test.md')

# 5 regression cases (1-indexed from input_data.json)
CASES = [
    {
        'index': 4,   # 1-indexed (#4)
        'label': '#4 B-TD',
        'description': '客户最后说"不用啦，我已经订好了"，买的是别家',
        'expected': 'drop',
        'expected_alt': [],
    },
    {
        'index': 8,   # #8
        'label': '#8 Q260117-Mr高',
        'description': '155条深度聊天，客户问过定金多少钱、讨论颜色面料，最近沉默',
        'expected': 'rush',
        'expected_alt': [],
    },
    {
        'index': 1,   # #1
        'label': '#1 Z26.01.20',
        'description': '37条聊天，客户已确认面料选布艺，等报价中',
        'expected': 'rush',
        'expected_alt': [],
    },
    {
        'index': 40,  # #40
        'label': '#40 z250822-小可',
        'description': '3条聊天，从未回复过任何消息，销售单方面发了三次促销',
        'expected': 'nurture',
        'expected_alt': ['drop'],
    },
    {
        'index': 50,  # #50
        'label': '#50 z251202-欢欢',
        'description': '13条聊天，客户预算四位数，报价16830，销售说做不到',
        'expected': 'drop',
        'expected_alt': [],
    },
]

MODEL_KEYS = ['deepseek', 'haiku', 'sonnet']


def run_single(model_key, customer):
    """Run one customer through one model. Returns dict with results."""
    model_cfg = MODELS[model_key]

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
        return {
            'model': model_key,
            'model_name': model_cfg['name'],
            'raw_output': resp['content'],
            'parsed': parsed,
            'input_tokens': resp['input_tokens'],
            'output_tokens': resp['output_tokens'],
            'elapsed': resp['elapsed'],
            'error': None,
        }
    except Exception as e:
        logger.error(f"  API error: {e}")
        return {
            'model': model_key,
            'model_name': model_cfg['name'],
            'raw_output': '',
            'parsed': None,
            'input_tokens': 0,
            'output_tokens': 0,
            'elapsed': 0,
            'error': str(e),
        }


def generate_report(all_results):
    """Generate markdown regression test report."""
    lines = []
    lines.append("# T-023b: Prompt回归测试报告")
    lines.append("")
    lines.append("> 执行时间: " + time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()))
    lines.append("> Prompt版本: 4-action体系 (rush/revive/nurture/drop)")
    lines.append("> 测试范围: 5 cases × 3 models = 15次调用")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Summary table
    lines.append("## 1. 回归测试结果")
    lines.append("")
    lines.append("| Case | 客户 | 模型 | 期望action | 实际action | reason | do_this | 通过? |")
    lines.append("|------|------|------|-----------|-----------|--------|---------|-------|")

    model_pass = {k: 0 for k in MODEL_KEYS}
    model_total = {k: 0 for k in MODEL_KEYS}

    for case_result in all_results:
        case = case_result['case']
        for r in case_result['results']:
            model_total[r['model']] += 1
            parsed = r['parsed']
            if parsed is None:
                actual = 'PARSE_FAIL'
                reason = '-'
                do_this = '-'
                passed = False
            else:
                actual = parsed.get('action', '?')
                reason = parsed.get('reason', '-')
                do_this = parsed.get('do_this', '-')
                valid_actions = [case['expected']] + case['expected_alt']
                passed = actual in valid_actions

            if passed:
                model_pass[r['model']] += 1

            pass_mark = 'PASS' if passed else 'FAIL'
            lines.append(f"| {case['label']} | {case['description'][:20]}... | {r['model_name']} | {case['expected']} | {actual} | {reason} | {do_this} | {pass_mark} |")

    lines.append("")
    lines.append("## 2. 模型通过率汇总")
    lines.append("")
    lines.append("| 模型 | 通过数 | 总数 | 通过率 |")
    lines.append("|------|-------|------|--------|")

    all_pass = True
    for mk in MODEL_KEYS:
        model_name = MODELS[mk]['name']
        p = model_pass[mk]
        t = model_total[mk]
        rate = f"{p}/{t} ({p*100//t}%)" if t > 0 else "N/A"
        lines.append(f"| {model_name} | {p} | {t} | {rate} |")
        if p < t:
            all_pass = False

    lines.append("")

    # Verdict
    lines.append("## 3. 结论")
    lines.append("")
    for mk in MODEL_KEYS:
        model_name = MODELS[mk]['name']
        p = model_pass[mk]
        t = model_total[mk]
        if p == t:
            lines.append(f"- **{model_name}**: 回归通过 ({p}/{t})，可以跑全量")
        else:
            lines.append(f"- **{model_name}**: 未完全通过 ({p}/{t})，需分析失败case")

    # Failure analysis
    lines.append("")
    lines.append("## 4. 失败case分析")
    lines.append("")

    has_failures = False
    for case_result in all_results:
        case = case_result['case']
        for r in case_result['results']:
            parsed = r['parsed']
            if parsed is None:
                actual = 'PARSE_FAIL'
            else:
                actual = parsed.get('action', '?')
            valid_actions = [case['expected']] + case['expected_alt']
            if actual not in valid_actions:
                has_failures = True
                lines.append(f"### {case['label']} × {r['model_name']}")
                lines.append(f"- 期望: {case['expected']} (也接受: {case['expected_alt'] or '无'})")
                lines.append(f"- 实际: {actual}")
                if parsed:
                    lines.append(f"- reason: {parsed.get('reason', '-')}")
                    lines.append(f"- do_this: {parsed.get('do_this', '-')}")
                    lines.append(f"- risk: {parsed.get('risk', '-')}")
                lines.append(f"- 原始输出:")
                lines.append(f"```")
                lines.append(r['raw_output'][:500])
                lines.append(f"```")
                lines.append("")

    if not has_failures:
        lines.append("无失败case。")

    # Detailed outputs
    lines.append("")
    lines.append("## 5. 完整输出记录")
    lines.append("")

    for case_result in all_results:
        case = case_result['case']
        customer = case_result['customer']
        lines.append(f"### {case['label']} ({customer.get('remark', '')})")
        lines.append(f"- wechat_id: `{customer.get('wechat_id', '')}`")
        lines.append(f"- 销售: {customer.get('sales_name', '')}, 层级: {customer.get('stratum', '')}, 消息数: {customer.get('msg_count', 0)}, 已报价: {customer.get('has_quote', False)}")
        lines.append(f"- 期望action: **{case['expected']}**")
        lines.append("")

        for r in case_result['results']:
            lines.append(f"**{r['model_name']}** ({r['elapsed']}s, {r['input_tokens']}+{r['output_tokens']} tokens)")
            lines.append(f"```json")
            lines.append(r['raw_output'][:800])
            lines.append(f"```")
            lines.append("")
        lines.append("---")
        lines.append("")

    # Cost summary
    lines.append("## 6. 费用汇总")
    lines.append("")
    lines.append("| 模型 | Input Tokens | Output Tokens | 耗时 | 估算费用(USD) |")
    lines.append("|------|-------------|---------------|------|--------------|")

    for mk in MODEL_KEYS:
        model_name = MODELS[mk]['name']
        total_in = sum(r['input_tokens'] for cr in all_results for r in cr['results'] if r['model'] == mk)
        total_out = sum(r['output_tokens'] for cr in all_results for r in cr['results'] if r['model'] == mk)
        total_time = sum(r['elapsed'] for cr in all_results for r in cr['results'] if r['model'] == mk)
        price_in = MODELS[mk]['price_input']
        price_out = MODELS[mk]['price_output']
        cost = (total_in * price_in + total_out * price_out) / 1_000_000
        lines.append(f"| {model_name} | {total_in} | {total_out} | {total_time:.1f}s | ${cost:.4f} |")

    return '\n'.join(lines)


def main():
    # Load input data
    input_path = os.path.join(DATA_DIR, 'input_data.json')
    logger.info(f"Loading input data from {input_path}")
    with open(input_path, 'r', encoding='utf-8') as f:
        input_data = json.load(f)

    logger.info(f"Loaded {len(input_data)} customers")

    # Verify API keys
    deepseek_key = os.getenv('DEEPSEEK_API_KEY', '')
    anthropic_key = os.getenv('ANTHROPIC_API_KEY', '')
    logger.info(f"DEEPSEEK_API_KEY: {'set' if deepseek_key else 'MISSING'}")
    logger.info(f"ANTHROPIC_API_KEY: {'set' if anthropic_key else 'MISSING'}")

    if not deepseek_key or not anthropic_key:
        logger.error("Both API keys required. Set DEEPSEEK_API_KEY and ANTHROPIC_API_KEY env vars.")
        sys.exit(1)

    all_results = []

    for case in CASES:
        idx = case['index'] - 1  # convert to 0-indexed
        customer = input_data[idx]
        logger.info(f"\n=== {case['label']} (expected: {case['expected']}) ===")

        case_results = []
        for mk in MODEL_KEYS:
            logger.info(f"  Running {MODELS[mk]['name']}...")
            result = run_single(mk, customer)
            case_results.append(result)

            if result['parsed']:
                actual = result['parsed'].get('action', '?')
                valid = [case['expected']] + case['expected_alt']
                status = 'PASS' if actual in valid else 'FAIL'
                logger.info(f"    -> action={actual} (expected={case['expected']}) [{status}]")
            elif result['error']:
                logger.info(f"    -> ERROR: {result['error']}")
            else:
                logger.info(f"    -> PARSE_FAIL")

            # 1 second delay between API calls
            time.sleep(1)

        all_results.append({
            'case': case,
            'customer': customer,
            'results': case_results,
        })

    # Generate report
    logger.info("\nGenerating report...")
    report = generate_report(all_results)

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, 'w', encoding='utf-8') as f:
        f.write(report)
    logger.info(f"Report saved to {REPORT_PATH}")

    # Also save raw results
    raw_path = os.path.join(DATA_DIR, 'regression_t023b_results.json')
    raw_data = []
    for cr in all_results:
        raw_data.append({
            'case_label': cr['case']['label'],
            'expected': cr['case']['expected'],
            'wechat_id': cr['customer']['wechat_id'],
            'results': [{
                'model': r['model'],
                'parsed': r['parsed'],
                'raw_output': r['raw_output'],
                'elapsed': r['elapsed'],
                'input_tokens': r['input_tokens'],
                'output_tokens': r['output_tokens'],
            } for r in cr['results']]
        })
    with open(raw_path, 'w', encoding='utf-8') as f:
        json.dump(raw_data, f, ensure_ascii=False, indent=2)
    logger.info(f"Raw results saved to {raw_path}")

    # Print summary
    print("\n" + "=" * 60)
    print("REGRESSION TEST SUMMARY")
    print("=" * 60)
    for mk in MODEL_KEYS:
        model_name = MODELS[mk]['name']
        passed = sum(1 for cr in all_results for r in cr['results']
                     if r['model'] == mk and r['parsed'] and
                     r['parsed'].get('action') in [cr['case']['expected']] + cr['case']['expected_alt'])
        total = sum(1 for cr in all_results for r in cr['results'] if r['model'] == mk)
        status = "ALL PASS" if passed == total else f"{passed}/{total}"
        print(f"  {model_name}: {status}")
    print("=" * 60)


if __name__ == '__main__':
    main()
