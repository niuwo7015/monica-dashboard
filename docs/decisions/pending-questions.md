# Pending Questions — 待人工决策

> Agent Teams 遇到需要 Woniu 决策的问题，追加到此文件。
> Woniu 在 claude.ai 讨论后，将决策结果更新到 decisions-v11.md 或新建决策文件。
> 已解决的问题移到底部"已解决"区域，保留记录。

---

## 待决策

### PQ-002: backfill群聊历史数据不完整（2026-03-08）

- **发现**：backfill在群 `44769956465@chatroom` 上因"时间格式有误"卡死
- **时间戳**：1759852800 / 1760457600（约2025年10月，可能超出API 6个月保留期）
- **需要决策**：
  1. 是否需要修复backfill脚本的时间窗口逻辑，跳过过期数据？
  2. 群聊历史数据对Phase 1规则引擎是否必要（Phase 1只管私聊跟进）？

---

## 已解决

### PQ-001: contacts表数据量严重不足 → M-019已修复（2026-03-08）

- **根因**：supabase-py v2的SELECT查询在HTTP/2连接复用下返回错误结果，导致upsert逻辑永远走UPDATE分支
- **修复**：用batch `.upsert(on_conflict)` 替代 `GET+INSERT/UPDATE`
- **结果**：contacts从119条恢复到13,826条
