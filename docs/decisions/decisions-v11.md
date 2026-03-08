# v11 决策确认 · 2026-03-07

> 本文件由 claude.ai 圆桌讨论产出，Agent Teams lead 必须读取并遵守。
> 状态：已确认，可执行

---

## 一、v10→v11 七项决策

| # | 议题 | 决策 | 说明 |
|---|------|------|------|
| 1 | 知识库三件套（核心经验摘要/完整知识库/典型案例库） | **直接沿用，不迭代** | Phase 1不调AI，知识库暂无消费方。Phase 2上线时再审 |
| 2 | AB测试（Opus vs DeepSeek） | **推迟到Phase 2跑稳后** | 触发条件：Opus跑满1个月+≥200次诊断。不设固定日期 |
| 3 | 客户级别（S/A/B/C） | **彻底砍掉** | V6已用probe体系替代。Phase 1管"有没有跟进"，不需要分级 |
| 4 | 587成交客户回溯 | **沿用v10的348人结果** | 已在知识库中沉淀。标记为"v10产出、待Phase 3验证" |
| 5 | SOP版本 | **继续用v3.1** | 等Phase 2 AI建议上线后，AI输出替代部分SOP功能，届时再重写 |
| 6 | 订单数据来源 | **Monica手动提供Excel导入** | 格式：客户微信号+下单日期+金额+产品线，四列。每周或双周一次 |
| 7 | 仪表盘设计 | **统一SalesToday一个入口** | 内部分tab：今日任务、客户列表、数据看板。不要多个网址 |

---

## 二、架构确认（从roadmap-v1继承）

- **四层系统**：no-miss规则引擎 → AI状态摘要 → 执行追踪 → 深层心理分析
- **Phase 1 = 纯规则引擎**：零AI，只管"有没有跟进"
- **模型策略**：Phase 2起用Opus 4.6，跑稳后A/B测试DeepSeek V3.2
- **诊断引擎**：V6 probe体系（probe_need, probe_objection, probe_silent, probe_advance, probe_value, probe_decision_maker）
- **全部运行在阿里云119.23.44.77**，不保留本地D盘架构
- **GitHub niuwo7015/monica-dashboard 为唯一代码仓库**

---

## 三、系统设计原则（不可违反）

1. 永远不推荐寄样或线下见面，除非客户主动要求
2. 永远报价（作为探测工具）
3. "永远不等，保持连接"——只有客户明确表达反感才冻结
4. 价值钩子只在首次接触、沉默激活、重大推进点使用，不是每次互动都用
5. 竞品探测在probe_objection内用帮助性框架处理
6. action_content ≤ 50字符
7. 客户问实体店 = 信任验证信号，不是真要去门店
8. 消息内容不匹配导致沉默，不是消息量
9. 确认风格/方案必须先于产品推荐；分享参考图 ≠ 确认整体风格
10. 短回复 = 兴趣下降，必须读言外之意

---

## 四、Phase 1 目标

- **核心指标**：跟进覆盖率从39%提升到70%+
- **机制**：规则引擎每日扫描全部客户，生成daily_tasks
- **规则逻辑**：基于最后互动时间、消息方向（mine/customer）、沉默天数
- **输出**：每个销售每天一份任务清单，通过SalesToday展示
- **不涉及**：AI诊断、AI话术建议、客户心理分析（这些是Phase 2）

---

## 五、当前数据状态（截至2026-03-07）

| 资源 | 状态 |
|------|------|
| chat_messages | ~4,300条（backfill新版M-006已部署，正在回补） |
| contacts | 6个销售号全部同步完成（~13,000+） |
| group_customer_mapping | 窗口D正在填充 |
| daily_tasks | 空，待Phase 1规则引擎填充 |
| orders | 空，待Monica提供Excel |
| cron增量拉取 | 暂停（让backfill独占API），backfill完成后恢复 |

---

## 六、待解决的技术前置

1. **backfill完成**：确认chat_messages数据量足够支撑规则引擎
2. **恢复cron**：backfill完成后执行 `crontab -l | sed 's/^#0/0/' | crontab -`
3. **orders表导入**：等Monica提供Excel，写导入脚本
4. **飞书webhook配置**：Woniu建飞书机器人，配置告警通知
5. **Supabase RLS**：Phase 1阶段做Auth体系

---

## 七、通信协议

- **决策文档**（本文件）由 claude.ai 产出 → 存入 `docs/decisions/`
- **执行报告** 由 Agent Teams 产出 → 存入 `docs/execution-reports/`
- **需要人工决策时** Agent Teams 输出问题到 `docs/decisions/pending-questions.md`
- **Woniu** 定期查看 pending-questions.md，在 claude.ai 讨论后更新决策文档
