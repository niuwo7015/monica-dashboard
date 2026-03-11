# Pending Questions — 待人工决策

> Agent Teams 遇到需要 Woniu 决策的问题，追加到此文件。
> Woniu 在 claude.ai 讨论后，将决策结果更新到 decisions-v11.md 或新建决策文件。
> 已解决的问题移到底部"已解决"区域，保留记录。

---

## 待决策

### PQ-008: rpc/dashboard_coverage 函数超时（2026-03-12，API验证）

**背景**: 对 Supabase API 进行连通性验证时，`rpc/dashboard_coverage` 返回 HTTP 500，错误码 PostgreSQL 57014（statement timeout）。其余4个查询（orders、contacts、daily_tasks、orders count）均正常返回 200。

**现象**:
- 错误信息：`{"code":"57014","message":"canceling statement due to statement timeout"}`
- 函数已部署（见 PQ-007 已解决记录），但执行时超时

**可能原因**:
1. 函数内部SQL做了全表扫描（chat_messages、contacts 数据量大），缺少合适索引
2. Supabase anon 角色的 `statement_timeout` 设置过短
3. 函数逻辑本身复杂度过高，需要拆分或缓存

**待决策**:
1. 是否需要优化 `dashboard_coverage()` 函数的 SQL 查询（加索引、缩小扫描范围）？
2. 是否允许调高 anon 角色的 statement_timeout？（需 Supabase Dashboard 操作）
3. 如果函数无法在 timeout 内完成，是否考虑改用预聚合表（materialized view 或定时写入汇总表）？

**影响**: Dashboard 覆盖率模块无法正常加载数据。

**详情**: API验证 curl 测试，2026-03-12

---

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

### PQ-007: SQL函数部署到Supabase → 已执行（2026-03-12）

- **执行**：通过 Supabase SQL Editor 执行 `sql/t022_dashboard_functions.sql`
- **修复**：`msg_content` 列不存在，改用 `COALESCE(cm.content, '[媒体消息]')`
- **结果**：3个函数 + 1个索引 + 3个GRANT 全部成功
- **已部署函数**：`dashboard_coverage()`, `dashboard_funnel_conversations()`, `dashboard_last_messages()`

### PQ-006: orders表字段名确认 → 已解决（2026-03-12）

- **确认**：实际字段名为 `order_stage`，值域为 `'deposit'`（付定金）和 `'won'`（成交）
- **SQL文件 s006 已过时**：s006中写的 `order_status` 不是当前线上字段
- **前端处理**：Dashboard代码主路径直接用 `order_stage`，无需修改

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
