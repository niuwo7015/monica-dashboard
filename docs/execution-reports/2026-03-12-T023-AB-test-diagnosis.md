# T-023: AI诊断A/B测试 — 执行报告

> 执行时间: 2026-03-12 03:51 ~ 04:20 (UTC)
> 执行者: Claude Agent
> 状态: **部分完成** (DeepSeek完成，Anthropic模型被阻断)

---

## 1. 执行摘要

### 完成项
- 分层抽样选取50个测试客户
- 准备50个客户的聊天记录输入数据
- DeepSeek V3.2 (reasoner) 完成全部50个客户诊断，0错误
- 脚本 `scripts/ab_test_diagnosis.py` 已push到GitHub

### 阻断项
- **Haiku 4.5 和 Sonnet 4.6 无法从阿里云服务器访问 api.anthropic.com**
- 返回 HTTP 403 "Request not allowed"
- 原因：中国大陆阿里云服务器无法直连 Anthropic API
- **需要人工决策**：配置代理或使用海外中转服务器

## 2. 客户抽样结果

从3188个有聊天记录的非成交客户中，按以下分层抽取50人：

| 层级 | 条件 | 目标 | 实际选中 |
|------|------|------|----------|
| 深度(deep) | ≥30条消息 | 10人 | 10人 |
| 中等(medium) | 10-29条消息 | 15人 | 15人 |
| 浅度(shallow) | 3-9条消息 | 15人 | 15人 |
| 已报价(quoted) | has_quote=true | 10人 | 10人 |

各销售分布：
- 小杰: 深度4 + 中等5 + 浅度5 + 已报价4 = 18人
- 可欣: 深度3 + 中等5 + 浅度5 + 已报价3 = 16人
- 霄剑: 深度3 + 中等5 + 浅度5 + 已报价3 = 16人

候选池充裕（deep层共1187人，medium层666人，shallow层434人，quoted层1258人）。

## 3. DeepSeek V3.2 (reasoner) 结果

### 3.1 成本与性能

| 指标 | 值 |
|------|-----|
| Input Tokens | 40,147 |
| Output Tokens | 55,310 (含reasoning tokens) |
| 总耗时 | 1,266.9s (~21分钟) |
| 平均每客户 | 25.3s |
| 费用(USD) | $0.0345 |
| 费用(CNY) | ≈¥0.25 |
| JSON解析成功率 | 50/50 (100%) |
| API错误数 | 0 |

注：DeepSeek reasoner的output_tokens包含reasoning_tokens（思维链），但不额外计费。

### 3.2 阶段分布

| 阶段 | 客户数 | 占比 |
|------|--------|------|
| 报价阶段 | 19 | 38% |
| 明确拒绝 | 7 | 14% |
| 沉默流失 | 7 | 14% |
| 初次接触 | 5 | 10% |
| 需求了解 | 5 | 10% |
| 产品推荐 | 3 | 6% |
| 已成交 | 2 | 4% |
| 尾款跟进 | 1 | 2% |
| 面料选择 | 1 | 2% |
| 尺寸确认 | 1 | 2% |

### 3.3 成交概率分布

| 概率 | 客户数 |
|------|--------|
| 高 | 9 (18%) |
| 中 | 25 (50%) |
| 低 | 16 (32%) |

### 3.4 初步质量观察

**优点**：
- JSON输出格式100%正确，无解析失败
- 阶段判断整体合理（报价阶段最多符合已报价客户居多的抽样特征）
- 建议具体可执行，能区分不同场景
- 明确拒绝和沉默流失的识别准确

**值得关注**：
- 2个"已成交"判断需验证（D-25.0717和D25.10.28），因抽样时已排除orders表记录
- 50%客户被判断为"中"概率，区分度偏低
- reasoner模式的thinking tokens较多，导致耗时较长（平均25s/客户）

### 3.5 成本推算（全量）

如果对全部3188个有聊天记录的客户跑DeepSeek诊断：
- 预计费用：3188/50 × $0.0345 ≈ **$2.20 (≈¥15.8)**
- 预计耗时：3188 × 25.3s ≈ **22.4小时**（串行）

## 4. Anthropic API 阻断情况

### 错误详情
```
HTTP/1.1 403 Forbidden
{'error': {'type': 'forbidden', 'message': 'Request not allowed'}}
```

### 原因分析
阿里云深圳机房 (119.23.44.77) 在中国大陆，无法直连 api.anthropic.com。
这是网络层面的限制，与API Key无关。

### 解决方案选项（需人工决策）

| 方案 | 复杂度 | 成本 |
|------|--------|------|
| A. 配置HTTP代理 | 低 | 需已有代理服务 |
| B. 使用海外VPS中转 | 中 | ~$5/月 |
| C. 使用Anthropic API兼容的国内中转服务 | 低 | 可能有加价 |
| D. 本地运行(Windows) | 低 | 无额外成本 |

## 5. 文件清单

| 文件 | 说明 |
|------|------|
| `scripts/ab_test_diagnosis.py` | A/B测试脚本（已push） |
| `data/ab_test/sample_customers.json` | 50个抽样客户列表（服务器） |
| `data/ab_test/input_data.json` | 50个客户的聊天记录输入（服务器） |
| `data/ab_test/results_deepseek.json` | DeepSeek诊断结果（服务器） |
| `data/ab_test/results_haiku.json` | Haiku结果（全部403错误） |

## 6. 下一步

1. **人工决策**：选择Anthropic API访问方案（上述A/B/C/D之一）
2. 配置好后，运行：
   ```bash
   python ab_test_diagnosis.py --run --model haiku
   python ab_test_diagnosis.py --run --model sonnet
   python ab_test_diagnosis.py --report
   ```
3. 三个模型跑完后再生成完整对比报告
