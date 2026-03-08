# Phase 1 Agent Teams 任务清单

> 本文件定义 Phase 1 的全部执行任务。
> Agent Teams lead 按优先级分派给 teammates 并行执行。
> 需要人工决策的节点已标注 ⚠️DECISION。

---

## 前置任务（必须先完成）

### M-009: 确认backfill状态并恢复cron
- 检查 `/var/log/monica/backfill.log`，确认backfill是否还在运行
- 查 `chat_messages` 总条数，评估数据是否足够
- 如果backfill已完成或卡住：恢复cron定时任务
  ```bash
  crontab -l | sed 's/^#0 \* \* \* \*/0 * * * */' | crontab -
  ```
- 输出：chat_messages的按月分布统计，写入执行报告

### M-010: 窗口D收尾确认
- 检查 group_customer_mapping 表是否已填充
- 如果未完成，执行 `scripts/fill_group_mapping.py`（注意supabase-py v2兼容性）
- 输出：contacts总数、group_customer_mapping总数，写入执行报告

### M-011: 建立文件协议目录
- 在GitHub仓库中创建：
  ```
  docs/decisions/           # 放入 decisions-v11.md
  docs/execution-reports/   # 空目录，加 .gitkeep
  docs/decisions/pending-questions.md  # 初始化为空模板
  ```
- 更新仓库根目录的 CLAUDE.md
- push到GitHub

---

## Phase 1 核心任务

### M-012: 设计规则引擎逻辑
- 读取 `docs/decisions/decisions-v11.md` 中的Phase 1目标和系统设计原则
- 设计规则：
  - 输入：chat_messages（最后互动时间、方向）、contacts（客户信息）
  - 输出：daily_tasks（每个销售每天的任务清单）
  - 规则示例：
    - 客户最后消息>3天且最后一条是客户发的 → 需要跟进
    - 客户最后消息>7天 → 紧急跟进
    - 销售最后消息>3天且客户未回 → 判断是否需要换话题切入
    - 新加好友48小时内未发首条消息 → 立即触达
- ⚠️DECISION：具体规则阈值（3天/7天等）需要确认，写入pending-questions.md
- 输出：规则引擎设计文档 + pending-questions.md

### M-013: 实现规则引擎脚本
- 依赖：M-012的规则设计确认后
- 写 `scripts/generate_daily_tasks.py`
- 读chat_messages和contacts，按规则生成daily_tasks记录
- 部署到阿里云cron（每天早上7:00运行）
- 输出：脚本+cron配置+测试结果

### M-014: 订单导入模板和脚本
- 创建Excel模板：客户微信号、下单日期、金额、产品线（四列）
- 写 `scripts/import_orders.py`：读取Excel，写入orders表
- ⚠️DECISION：模板给Monica确认格式是否可行
- 输出：模板文件 + 导入脚本

### M-015: SalesToday前端 — 今日任务页
- 读取daily_tasks表，展示每个销售的当日任务
- 要求：
  - 视觉简洁，大字体，扫一眼就能看懂
  - 按紧急程度排序（红/黄/绿）
  - 每条任务显示：客户名、沉默天数、最后一条消息摘要、建议动作
  - 建议动作 ≤ 50字符
- ⚠️DECISION：UI设计稿需要确认后再开发
- 输出：前端代码 + 截图

### M-016: SalesToday前端 — 客户列表页
- 读取contacts表，展示全部客户
- 支持按销售筛选、按标签筛选、按最后互动时间排序
- 点击客户可看最近聊天摘要
- 输出：前端代码

### M-017: SalesToday前端 — 数据看板页
- 展示核心指标：
  - 跟进覆盖率（当前 vs 目标70%）
  - 各销售的跟进率对比
  - 沉默客户数量趋势
  - 每日新增客户数
- 输出：前端代码

### M-018: 飞书告警配置
- ⚠️DECISION：需要Woniu先创建飞书机器人，提供webhook URL
- 配置告警：
  - 每天早上推送：今日任务汇总
  - 异常告警：cron失败、API限流、数据库写入失败
- 输出：告警脚本 + 配置文档

---

## 执行顺序建议

```
并行1: M-009 + M-010 + M-011（前置收尾）
    ↓
并行2: M-012（规则设计）+ M-014（订单模板）
    ↓ M-012确认后
并行3: M-013（规则引擎实现）+ M-015/M-016/M-017（前端三页）
    ↓
M-018（飞书告警，等webhook URL）
```

---

## 完成标准

Phase 1 完成 = 以下全部满足：
1. 规则引擎每天7:00自动生成daily_tasks
2. SalesToday能展示今日任务、客户列表、数据看板
3. 跟进覆盖率可量化测量（有基线数据）
4. cron稳定运行无报错
5. Monica和销售团队开始使用SalesToday
