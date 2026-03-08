# Pending Questions — 待人工决策

> Agent Teams 遇到需要 Woniu 决策的问题，追加到此文件。
> Woniu 在 claude.ai 讨论后，将决策结果更新到 decisions-v11.md 或新建决策文件。
> 已解决的问题移到底部"已解决"区域，保留记录。

---

## 待决策

### PQ-005: daily_tasks表缺少前端需要的展示字段（2026-03-09）

- **现状**：L-002任务spec提到daily_tasks应包含`silent_days`、`last_message_preview`、`action_suggestion`字段，但实际表和generate脚本中均没有这些字段
- **当前处理**：前端从`trigger_rule`中解析沉默天数，从`task_type`派生建议动作文案，不显示最后消息摘要
- **需要决策**：
  1. 是否需要在generate_daily_tasks.py中增加这3个字段的生成逻辑？（需ALTER TABLE）
  2. `last_message_preview`需要查chat_messages取最新一条内容，会增加脚本运行时间
  3. `action_suggestion`是否由规则引擎硬编码，还是将来让AI生成？

### PQ-006: initial_contact任务量过大导致前端数据量大（2026-03-09）

- **现状**：backfill仍在运行（30K/100K+），9,620个contacts无聊天记录 → 生成9,620条initial_contact任务
- **影响**：前端一次加载3,000+任务，渲染性能和体验受影响
- **需要决策**：
  1. 是否在前端按优先级分页（只显示urgent/high，initial_contact折叠或默认隐藏）？
  2. 是否在generate脚本中过滤掉initial_contact（等backfill完成后再开启）？
  3. 是否设置单日任务数上限（如每个销售最多100条）？

### PQ-002: backfill群聊历史数据不完整（2026-03-08）

- **发现**：backfill在群 `44769956465@chatroom` 上因"时间格式有误"卡死
- **时间戳**：1759852800 / 1760457600（约2025年10月，可能超出API 6个月保留期）
- **需要决策**：
  1. 是否需要修复backfill脚本的时间窗口逻辑，跳过过期数据？
  2. 群聊历史数据对Phase 1规则引擎是否必要（Phase 1只管私聊跟进）？

---

## 已解决

### PQ-004: daily_tasks表增加wechat_id字段 → S-003已执行（2026-03-08）

- **决策**：同意给daily_tasks表增加contact_wechat_id和sales_wechat_id字段
- **执行**：ALTER TABLE已在Supabase SQL Editor执行，索引已创建
- **验证**：generate_daily_tasks.py dry-run通过，9,842条任务正确生成

### PQ-003: 用wechat_id作为关联键 → S-003已落地（2026-03-08）

- **决策**：规则引擎用wechat_id作为关联键，不依赖customer_id
- **执行**：generate_daily_tasks.py基于contacts.wechat_id + chat_messages关联，不依赖customer_id
- **验证**：dry-run成功覆盖9,843个contacts（排除群聊的非删除好友）

### PQ-001: contacts表数据量严重不足 → M-019已修复（2026-03-08）

- **根因**：supabase-py v2的SELECT查询在HTTP/2连接复用下返回错误结果，导致upsert逻辑永远走UPDATE分支
- **修复**：用batch `.upsert(on_conflict)` 替代 `GET+INSERT/UPDATE`
- **结果**：contacts从119条恢复到13,826条
