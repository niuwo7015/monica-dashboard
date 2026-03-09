# Pending Questions — 待人工决策

> Agent Teams 遇到需要 Woniu 决策的问题，追加到此文件。
> Woniu 在 claude.ai 讨论后，将决策结果更新到 decisions-v11.md 或新建决策文件。
> 已解决的问题移到底部"已解决"区域，保留记录。

---

## 待决策

### PQ-005: 是否启动按好友历史聊天回补？（2026-03-09，S-004）

**背景**: S-004探索确认records接口支持按个人好友拉取历史聊天记录（日期字符串格式），限流2秒/次。

**待决策**:
1. **是否启动？** — records只返回文本+语音，不返回图片/视频/文件。只有文本+语音是否足够有价值？
2. **回补范围？** — 全部6个月(~180天) vs 最近3个月(~90天)？全部好友 vs 只要活跃好友(有lastChatTime的)?
3. **优先级？** — 与Phase 1其他任务（规则引擎、飞书集成等）的优先级对比？API 3月20日到期。

**耗时预估**: 500活跃好友 × 60窗口 = 30,000次API调用 ≈ 25小时（3s/call）

**详情**: 见 `docs/execution-reports/2026-03-09-S004-yunke-api-exploration.md`

---

## 已解决

### PQ-002: backfill群聊历史数据不完整（2026-03-08）→ 已决策（2026-03-09）

- **决策**：Phase 1跳过群聊回补，不阻塞主线。但单独派任务深度调查群聊数据拉取方案。
- **调查任务**：S-007，见 docs/tasks/S-007-群聊回补调查.md
- **原因**：Phase 1只管私聊跟进，群聊数据不影响规则引擎运行

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
