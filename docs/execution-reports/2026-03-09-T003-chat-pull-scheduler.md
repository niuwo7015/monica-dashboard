# T-003 聊天记录拉取统一调度 — 执行报告

**日期**: 2026-03-09
**任务代号**: T-003
**状态**: 回补进行中

---

## 执行摘要

1. **T-001进程已停止**: kill PID 77118 (yunke_allrecords_fullsync.py)
2. **v2脚本已部署**: 服务器 + GitHub仓库 scripts/yunke_pull_chat_v2.py
3. **v2回补已启动**: PID 79823, nohup后台运行
4. **cron已配置**: v2增量行已添加（注释状态，等回补完启用）

## chat_messages表当前状态

| 指标 | 值 |
|------|------|
| 总条数 | 215,162 |
| 最早记录 | 2024-05-09 06:39 UTC |
| 最新记录 | 2026-03-09 03:22 UTC |

> T-001已回补到2024-05-09，比目标2024-09-01更早。v2回补从2024-09-01开始会快速跳过已有数据（upsert去重），主要补齐可能的空洞。

## v2回补参数

```
python3 yunke_pull_chat_v2.py --backfill --start 2024-09-01
```

- 需扫描约 13,309 小时窗口
- 指数跳跃加速空窗口（1h→2h→4h→24h→72h）
- 断点续传文件: `.backfill_cursor`
- 日志: `/var/log/monica/pull_chat_v2_backfill.log`

## v2脚本改进（相比v1）

- 纯allRecords模式（私聊+群聊全覆盖）
- 指数跳跃空窗口扫描（大幅减少API调用）
- 精确sleep（用elapsed计算，不浪费时间）
- 断点续传（状态文件存游标timestamp）
- 批量upsert 100条/批
- MIN_INTERVAL = 5.5秒（留余量）

## cron配置

```
# T-003 v2增量(回补完成后取消注释)
# 0 * * * * cd /home/admin/monica-scripts && python3 yunke_pull_chat_v2.py >> /var/log/monica/pull_chat.log 2>&1
```

**启用步骤**（回补完成后）：
1. 确认回补进程已结束: `ps aux | grep pull_chat_v2`
2. 编辑crontab: `crontab -e`
3. 取消注释v2增量行（删除行首 `# `）

## 待办

- [ ] 监控回补完成（预计数小时，视空窗口数量而定）
- [ ] 回补完成后启用cron增量
- [ ] 验证增量模式首次运行正常

## 旧脚本保留

- `yunke_pull_chat.py` — v1（已停用，cron注释）
- `yunke_allrecords_fullsync.py` — T-001全量回补（已停用）
