# CLAUDE.md — Monica销售AI系统

> Agent Teams lead 和所有 teammates 必须遵守本文件。
> 最后更新：2026-03-07

---

## 项目概述

Monica Mocha（莫妮卡摩卡）高端定制家具品牌的AI销售管理系统。
通过微信私域运营，用规则引擎+AI提升销售跟进覆盖率和转化率。

## 关键文件路径

```
docs/decisions/          # claude.ai产出的决策文档（只读，不要修改）
docs/execution-reports/  # Agent Teams产出的执行报告
docs/decisions/pending-questions.md  # 需要人工决策的问题
docs/roadmap/            # 路线图
docs/knowledge/          # 知识库和API文档
docs/handoff/            # 交接文件
scripts/                 # Python脚本（部署到阿里云 /home/admin/monica-scripts/）
sql/                     # 数据库schema
frontend/                # SalesToday前端
```

## 通信协议（必须遵守）

1. **启动时**：先读 `docs/decisions/` 下最新的决策文档，理解当前阶段目标和约束
2. **执行完成后**：输出执行报告到 `docs/execution-reports/YYYY-MM-DD-任务描述.md`
3. **遇到需要人工决策的问题**：追加到 `docs/decisions/pending-questions.md`，不要自行决定
4. **不要修改 `docs/decisions/` 下的决策文档**，那是 claude.ai 圆桌讨论的产出

## 需要人工决策的场景

- 架构变更（新增表、改字段、改接口）
- 面向销售团队的任何输出格式
- 涉及Monica审批的流程变更
- 成本超过预期的技术方案
- 任何不确定的业务逻辑

## 服务器信息

- 阿里云：119.23.44.77（admin用户，SSH密钥已配置）
- 脚本目录：/home/admin/monica-scripts/
- 日志目录：/var/log/monica/
- 数据库：Supabase（新加坡），URL见环境变量
- GitHub：niuwo7015/monica-dashboard

## 云客API使用规则（严格遵守）

- 调用间隔 ≥ 8秒，建议10秒
- 同一时间只能有一个脚本在调云客API
- 被限流时：sleep(60)后重试，不要缩短间隔
- 限流返回特征："请勿频繁操作"
- allRecords不返回群聊客户文本，群聊用records接口
- API数据保留约6个月

## 代码规范

- Python脚本：蛇形命名，yunke_前缀
- 数据库字段：蛇形英文，前端中文显示
- 所有任务带代号编号（M-XXX），方便追踪
- commit message包含任务代号
- 改完代码先push到GitHub，再部署到服务器

## 当前阶段：Phase 1（纯规则引擎）

目标：跟进覆盖率从39%→70%+
手段：规则引擎每日扫描，生成daily_tasks
不涉及：AI诊断、AI话术（Phase 2）

详细决策见 `docs/decisions/decisions-v11.md`
