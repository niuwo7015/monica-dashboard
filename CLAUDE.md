# CLAUDE.md — Monica销售AI系统

> Agent Teams lead 和所有 teammates 必须遵守本文件。
> 最后更新：2026-03-14

---

## 项目概述

Monica Mocha（莫妮卡摩卡）高端定制家具品牌的AI销售管理系统。
通过微信私域运营，用规则引擎+AI诊断提升销售跟进覆盖率和转化率。
核心问题：61%客户没有得到跟进。目标：覆盖率从39%→70%+。

## 当前阶段：Phase 2（AI诊断）

- **Phase 1规则引擎分类已取消**（urgent_reply/follow_up_silent/reactivate分类没有意义，直接用AI诊断结果）
- daily_tasks表仍由generate_daily_tasks.py生成，但分类结果将被AI诊断的4-action替代
- 当前重点：提示词v3修正 + 方案A测试验证 + 销售端卡片开发
- 最新完整交接见 `docs/handoff/full-context-20260314.md`

## AI诊断体系（5-action）

| action | 含义 | 销售端标签 | 颜色 |
|--------|------|-----------|------|
| rush | 客户有明确推进信号，今天就要回 | 🔴 立刻跟 | 红 |
| follow | 有兴趣但时机不急，有节奏地保持联系 | 🟠 持续跟 | 橙 |
| revive | 沉默了但之前有深度互动，值得主动激活 | 🟡 值得捞 | 黄 |
| nurture | 浅度接触或时机没到，低频维护 | ⚪ 低优养着 | 灰 |
| drop | 明确拒绝/不匹配/已买别家 | ⛔ 别浪费 | 暗灰 |

### 模型选择
- **Haiku 4.5** — 量产模型（4.4秒/客户，98%成功率）
- Anthropic直连，不走百炼
- DeepSeek V3.2走官方API（做对照组，55秒/客户太慢）
- Sonnet已淘汰（12%解析失败率）

### 诊断输出格式
```json
{
  "action": "rush|follow|revive|nurture|drop",
  "reason": "判断核心依据（20字内）",
  "do_this": "销售下一步具体动作（50字内）",
  "risk": "流失风险信号（没有则null，15字内）"
}
```

### 三层点评方案（已确定：1次CoT调用）
- 诊断(Haiku 1次) + 三层点评(Haiku 1次，prompt要求三段式输出：消费者→专家→综合)
- 共2次Haiku调用/客户（不是4次独立调用，经测试1次CoT和3次独立调用质量差异不大）
- 成本：约0.10元/客户，以11月真实数据77人/天计算约231元/月
- Monica认可综合判断的可信度最高

### Prompt状态
- prompt v2已完成T-029测试，20客户Monica标注10个，准确率37.5%（完全一致3/8）
- **需要修正为prompt v3**，解决T-029发现的5个规则问题（见下方）
- 渐进式测试计划：~~5案例→~~20客户(已完成)→50客户→200客户→全量
- `docs/diagnostics/stage_classification_prompt_v2.md` **已过时，不要用**

### T-029测试发现的5个提示词问题（需在v3中修正）
1. **规则4过于机械**：报价后沉默48h一律判revive，但客户态度"有空间就买"应降为nurture
2. **规则3不看时间线**：发户型图就判rush，但客户说"两个月后才需要"不应该急
3. **缺少"约了没来"降级规则**：约了展厅但回访无回应，应从rush降为revive
4. **风险解读方向错误**：客户沉默后主动回来询问=正面信号，risk应标"销售未回复X天"
5. **do_this不考虑客户兴趣点**：应识别客户生活方式线索（宠物/孩子/装修风格）定制建议

## 关键文件路径

```
docs/handoff/full-context-20260314.md  # 最完整的项目交接（以此为准）
docs/decisions/          # claude.ai产出的决策文档（只读，不要修改）
docs/execution-reports/  # Agent Teams产出的执行报告
docs/decisions/pending-questions.md  # 需要人工决策的问题
docs/roadmap/            # 路线图（部分内容已过时，以交接文档为准）
docs/knowledge/          # 知识库和API文档
docs/handoff/            # 交接文件
scripts/                 # Python脚本（部署到阿里云 /home/admin/monica-scripts/）
sql/                     # 数据库schema（可能过时，以Supabase实际为准）
frontend/                # SalesToday前端
```

## 通信协议（必须遵守）

1. **启动时**：先读 `docs/handoff/full-context-20260314.md` 获取完整上下文
2. **执行完成后**：输出执行报告到 `docs/execution-reports/YYYY-MM-DD-任务描述.md`
3. **遇到需要人工决策的问题**：追加到 `docs/decisions/pending-questions.md`，不要自行决定
4. **不要修改 `docs/decisions/` 下的决策文档**，那是 claude.ai 圆桌讨论的产出

## 需要人工决策的场景

- 架构变更（新增表、改字段、改接口）
- 面向销售团队的任何输出格式
- 涉及Monica审批的流程变更
- 成本超过预期的技术方案
- 任何不确定的业务逻辑
- **任何涉及生产数据源的写入操作**（飞书表格、Supabase生产表等）

## 服务器信息

- 阿里云：119.23.44.77（admin用户，SSH密钥 `~/.ssh/aliyun_jst`）
- 脚本目录：/home/admin/monica-scripts/
- 日志目录：/var/log/monica/
- 环境变量：/home/admin/monica-scripts/.env
- 数据库：Supabase（新加坡），项目ID: dieeejjzbhkpgxdhwlxf
- GitHub：niuwo7015/monica-dashboard
- 前端旧域名：monica-crm-eta.vercel.app（应统一到这个）

### 服务器环境变量（.env）— 本地运行脚本时需要设置

| 变量 | 值 | 用途 |
|---|---|---|
| SUPABASE_URL | `https://dieeejjzbhkpgxdhwlxf.supabase.co` | Supabase地址 |
| SUPABASE_SERVICE_ROLE_KEY | `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRpZWVlamp6YmhrcGd4ZGh3bHhmIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3MjI5ODQyNywiZXhwIjoyMDg3ODc0NDI3fQ.sMo0KefhbdA1F-8bS0ESIB_0HXxJHdmH18xO0oCdUco` | Supabase全权限 |
| ANTHROPIC_API_KEY | `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` | Claude Haiku 4.5直连 |
| ANTHROPIC_PROXY | `http://127.0.0.1:7897` | Clash代理（中国IP被Anthropic封） |
| DASHSCOPE_API_KEY | `sk-a5f9278bbbc34af7b5e608111cee1c68` | 阿里云百炼（语音转写paraformer-v2） |
| FEISHU_APP_ID / APP_SECRET | 见服务器.env | 飞书应用凭证（只读权限） |
| DEEPSEEK_API_KEY | 见服务器.env | DeepSeek V3.2官方API |

## Cron定时任务

| 时间 | 脚本 | 说明 |
|------|------|------|
| 每小时整点 | yunke_pull_chat_v2.py | 聊天增量+语音自动转写 |
| 每小时30分 | feishu_sync_wiki_orders.py | 飞书订单同步 |
| 每天7:00 | generate_daily_tasks.py | 生成每日任务（Phase 1分类已取消，待改为AI诊断驱动） |
| 每天7:10 | feishu_notify.py | 飞书每日任务推送（待改为推送AI诊断结果） |
| 每天7:30 | yunke_pull_friends.py | 好友同步 |
| 每天8:00/20:00 | transcribe_voice.py | 语音转写回补 |
| 每10分钟 | dashboard_cache.py | Dashboard缓存预计算 |
| 每天21:00 | mark_tasks_done.py | 自动标记已跟进任务 |
| 每天21:30 | system_report.py | 系统运维报告推送飞书 |

所有cron命令必须带 `set -a && source /home/admin/monica-scripts/.env && set +a &&` 前缀。

## 云客API使用规则（严格遵守）

- **API到期日：2027-03-20**（已续费1年）
- 调用间隔 ≥ 5秒（allRecords实测5秒可行，留余量用5.5秒）
- 同一时间只能有一个脚本在调云客API
- 被限流时：sleep(60)后重试，不要缩短间隔
- 限流返回特征："请勿频繁操作"
- **allRecords包含群聊消息（含mine=false），但不完整（丢失约39%）**
- 群聊完整数据需用records接口逐群补拉
- API数据保留约6个月
- timestamp参数：13位毫秒时间戳，需小于当前时间30分钟

## 数据关联规则（严格遵守）

- **全链路用 sales_wechat_id 关联，不用 sales_id**（orders.sales_id是UUID不是wxid）
- 群聊/私聊判断：用 `room_id LIKE '%@chatroom%'`，不用 `room_id IS NOT NULL`（room_id有污染）
- chat_messages有 `is_system_msg` 字段，查最后消息时必须过滤 `is_system_msg = false`
- 去重用 msg_svr_id 做唯一索引
- 群发消息标记[群发]，不算真正的销售跟进互动

## 三段式成交模型（严格遵守）

客户成交分三个阶段：
1. **付1000看小样**（order_stage=deposit, amount=1000）— 试探阶段
2. **付订金确认订单**（order_stage=won）— **中段，算成交时间点**
3. **付尾款发货** — 履约阶段

关键规则：
- **成交时间点 = won订单的order_date**（中段付订金确认）
- **成交周期(deal_cycle_days) = won的order_date - contacts.add_time（加微信日期）**
- **转化率时间筛选 = 用won订单的order_date过滤**，不用deposit日期
- deposit(amount≤1000)是看小样阶段，不算成交，不计算deal_cycle_days
- deposit(amount>1000)视同won，算成交

## 数据安全铁律

1. **禁止**对chat_messages执行TRUNCATE或DELETE全表
2. **禁止**飞书应用开写入权限（sheets:spreadsheet已关闭）
3. 任何批量删除/清空操作需要Woniu明确确认
4. 语音转写结果已写入content字段，重拉聊天记录时**不得覆盖**已有非空content
5. 生产数据源的写入操作需Woniu确认

## 飞书应用权限规则

- **只开读取权限**：sheets:spreadsheet:readonly + wiki:wiki:readonly
- **写入权限必须关闭**：sheets:spreadsheet 已关闭
- 任何涉及生产数据源的写入操作需Woniu明确确认

## Dashboard设计规范

- 背景：#111110（深色）
- 主色：#E8C47C（金色）
- 字体：DM Sans（数字）/ 系统中文（文字）
- 布局：540px单列，手机优先
- **所有界面文字必须中文，不允许出现英文**

## 系统设计原则（不可违反）

1. 永远不推荐寄样或线下见面，除非客户主动要求
2. 永远报价（报价是探测工具）
3. "永远不等，保持连接"——只有客户明确表达反感才冻结
4. 价值钩子只在首次接触、沉默激活、重大推进点使用
5. 竞品探测用帮助性框架处理
6. 建议动作不超过50字
7. 客户问实体店=信任验证信号
8. 消息内容不匹配导致沉默，不是消息量
9. 确认风格/方案必须先于产品推荐
10. 短回复=兴趣下降，必须读言外之意

## 代码规范

- Python脚本：蛇形命名，yunke_前缀
- 数据库字段：蛇形英文，前端中文显示
- 所有任务带代号编号（T-XXX），方便追踪
- commit message包含任务代号
- 改完代码先push到GitHub，再部署到服务器

## 验收规范（每个任务必须执行）

1. 改了cron → `crontab -l` 确认 + 手动跑一次看日志
2. 改了数据库 → SELECT实际查询确认
3. 部署了脚本 → source .env后手动跑一次确认无报错
4. 部署了前端 → 打开URL确认页面和数据正确
5. 改了字段映射 → dry-run确认对齐
6. 未经实际验证的任务不算完成

## 过时文件（不要参考）

- `docs/diagnostics/stage_classification_prompt_v2.md` — 旧12阶段，已被4-action替代
- `sql/` 建表脚本 — 字段名可能跟实际表不一致，以Supabase实际为准
- roadmap中提到的"Opus 4.6"和"DeepSeek A/B测试" — 已改为Haiku 4.5量产
- `decisions-v11.md`中Phase 1纯规则引擎 — 实际已进入Phase 2
- 百炼不能调Claude/DeepSeek，只能调千问和paraformer

## 常见陷阱（历史教训）

- cron不会自动source .env → 所有cron命令必须带 `set -a && source .env && set +a &&`
- 脚本字段名必须跟Supabase实际表核对，SQL建表脚本可能过时
- Vercel部署用旧项目 monica-crm-eta.vercel.app，不要新建
- orders.sales_id是UUID不是wxid
- allRecords API包含群聊消息但不完整（丢约39%）
- SABC客户分级已砍掉，用4-action probe体系替代

## 自动执行规则（不需要问Woniu，直接做）

### 规则1：每次完成任务后自动更新CLAUDE.md
完成任何任务后，把以下信息追加到CLAUDE.md的"最近变更"区块：
- 改了什么（文件名/表名/cron）
- 当前实际状态（数据数量/cron内容/部署URL）
- 遗留问题（如果有）
不要问是否需要更新，直接更新。

### 规则2：发现过时信息自动修正
在读取项目文件时如果发现文档内容跟实际代码/数据库/服务器状态不一致：
- 以实际状态为准
- 自动更新过时的文档
- 在回复中提一句"发现xxx文档过时，已更新"
不要问是否需要修正，直接修正。

### 规则3：上下文到65%自动交接
当上下文使用量达到65%时：
1. 自动把当前进展、未完成的事、关键发现写入 docs/handoff/auto-handoff-{日期}.md
2. 同步更新CLAUDE.md的"最近变更"区块
3. 告诉Woniu："上下文快满了，进展已保存到handoff文件，请开新会话继续"
不要等Woniu发现，主动处理。

### 规则4：遇到不确定的业务问题才问Woniu
以下情况自己决定，不要问：
- 技术方案选择（用RPC还是前端查询、用什么库、SQL怎么写）
- 文件怎么组织
- 代码风格
- 部署流程

以下情况必须问Woniu：
- 涉及Monica审批的流程变更
- 面向销售团队的输出格式/措辞
- 新增费用（比如开通新API）
- 删除或覆盖生产数据
- 业务逻辑判断（比如某个客户应该判rush还是revive）

### 规则5：复杂任务自动拆分
收到一个大任务时，自己拆成小步骤，一步一步执行：
1. 先分析问题
2. 列出执行计划
3. 按顺序执行，每步验证
4. 全部完成后给Woniu一个总结报告
不要问"先做哪个"，自己按依赖关系和优先级排序。

---

## 最近变更

### 2026-03-14
- **订单数据修复**：orders.sales_wechat_id回填946条（980→34条缺失，剩余是飞书脏数据）；feishu_sync_wiki_orders.py新增SALES_NAME_TO_WXID映射，新订单自动带sales_wechat_id
- **成交周期修正**：deal_cycle_days算法改为「加微信日期→中段付订金确认日期(won)」，deposit订单不算周期；backfill_deal_cycle.py已重写
- **三段式成交模型写入CLAUDE.md**：付1000看小样→付订金确认(成交时间点)→付尾款发货，转化率用中段时间点
- **Phase 1分类取消**：Woniu决定取消规则引擎的task_type分类（urgent_reply/follow_up_silent/reactivate），直接用Phase 2 AI诊断的4-action结果
- **三层点评方案确定**：采用方案A（全Haiku 4次独立调用），成本约0.19元/客户，443元/月（以11月77人/天计算）
- **T-029测试完成**：20客户AI诊断 + Monica标注10个对比，准确率37.5%，发现5个提示词问题待v3修正
- **诊断对比分析**：`C:\Users\woniu\Desktop\T029-诊断对比分析.md`，含逐条对比和提示词改进建议
- **5-action扩展**：新增follow（持续跟），介于rush和revive之间，用于客户有兴趣但时机不急的场景
- **待办**：修正提示词v3（含5-action） → 重跑测试客户 → 扩大到50客户验证
- **T-031 系统运维报告**：新增 system_report.py，每天21:30检查所有cron运行状态并推送飞书，cron已添加
- **语音转写修复**：transcribe_voice.py 失败的标记`[转写失败]`避免无限重试，已部署
- **数据库字段文档**：full-context-20260314.md 补充了 chat_messages 和 contacts 完整字段明细（已验证）

### 2026-03-13
- **crontab修复**：添加 `SHELL=/bin/bash` 到crontab顶部（修复source命令兼容性）；`feishu_sync_wiki_orders.py` 增加 `--all` 参数同步全部3个飞书表格
- 备份保存在服务器 `/tmp/crontab_backup.txt`
- `yunke_pull_chat_v2.py` 手动运行确认正常，增量模式无新数据（cron已在正常运行）
