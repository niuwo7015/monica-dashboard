# T-025: 管理层数据看板更新 — 执行报告

**日期**: 2026-03-12
**任务代号**: T-025
**状态**: 已完成，Vercel生产部署已验证

---

## 变更清单

### 1. 时间筛选器
- 去掉"全部"选项
- 新增7个预设: 今天 / 7天 / 14天 / 30天 / 本月 / 上月 / 自定义
- 自定义模式展开两个date picker（开始日期 至 结束日期）
- date picker使用dark colorScheme适配深色主题

### 2. 客户漏斗双视角
- 漏斗区块内顶部新增toggle: 按获客 / 按成交
- **按获客**（默认）:
  - 分母 = 选定时间内add_time的客户
  - 追踪这批人最终走到哪一步（成交可能在时间范围之后）
  - 加微信→有对话→已报价→付定金→成交
- **按成交**:
  - 每层只算选定时间内发生的动作
  - 加微信: add_time在范围内
  - 有对话: RPC dashboard_funnel_conversations
  - 已报价: contacts with has_quote=true AND add_time在范围内
  - 付定金: orders.order_stage IN ('deposit','won')
  - 成交: orders.order_stage = 'won'
- toggle样式沿用FilterBar的pill风格（rgba(232,196,124,0.15)选中态）

### 3. 漏斗总转化率
- 漏斗区块右上角显示大字总转化率（加微信→成交）
- 每层右侧新增两列指标:
  - ↓ xx%: 层间转化率（该层/上一层）
  - xx%: 总转化率（该层/第一层），颜色 rgba(255,255,255,0.2)

### 4. 沉默预警Top10
- 从5条扩展到10条
- 数据源: RPC dashboard_last_messages 查询最后互动时间（排除is_system_msg=true）
- 排除: 已成交客户（orders.order_stage='won'），销售微信号（SALES_LIST）
- 颜色阈值: >60天 #E85D5D, >30天 #E8C47C, 其他 rgba(255,255,255,0.4)
- 标题改为"沉默预警 · Top10"

### 5. 沉默预警WoW对比
- 卡片右上角显示: 本周新增沉默>14天 vs 上周同口径
- 本周 = 最后消息14-20天前（近7天跨过14天阈值的客户）
- 上周 = 最后消息21-27天前
- 本周>上周红色，反之绿色

### 6. 真实数据接入
- 覆盖率: daily_tasks表，今日done vs pending + RPC dashboard_coverage（fallback到contacts全量计数）
- 漏斗: contacts + RPC dashboard_funnel_conversations + orders联查（双模式）
- 业绩: orders表按order_date筛选，deposit/won用order_stage字段判断
- 销售跟进: daily_tasks按sales_wechat_id分组
- 风险信号: contacts(has_quote优先) + RPC dashboard_last_messages
- 销售名映射: SALES_LIST from theme.js
- 排除规则: won客户排除出风险信号，SALES_IDS排除出客户统计

### 7. 设计语言更新
- 背景 #111110, 主色 #E8C47C, 成功 #6BCB77, 危险 #E85D5D
- 漏斗色系: #7C9CE8, #8BC7E8, #E8C47C, #E8A84C, #6BCB77
- 字体 DM Sans (Google Fonts动态注入)
- 卡片 rgba(255,255,255,0.03) + rgba(255,255,255,0.06)
- 单列540px maxWidth

## 未改动项（按要求保留）
- 整体单列布局结构
- Header样式（App.jsx未修改）
- 覆盖率、业绩、销售跟进区块的UI结构（仅替换数据源和设计token）

## 修改文件
- `frontend/src/lib/dashboardQueries.js` — 查询层重构
- `frontend/src/pages/Dashboard.jsx` — UI层重构

## 部署
- Git commits: edea1ac (UI), fea047b (vercel.json SPA routing), 3c1415c (DB schema fix)
- 手动Vercel CLI部署（`vercel deploy --prod`，项目 monica-crm）
- 访问地址: https://monica-crm-eta.vercel.app/dashboard
- 别名: https://www.monicamocca.com

## 数据库Schema修正（3c1415c）
发现SQL定义文件 s006_orders_table.sql 与实际线上表结构不一致：
- `customer_wechat_id` → 实际为 `wechat_id`
- `sales_wechat_id` → 实际为 `sales_id`（UUID类型，非微信号）
- `product_line` → 实际为 `product`
- `order_status` → 实际为 `order_stage`（值域: 'deposit', 'won'）
- 额外字段: `deposit`, `balance`, `payment_status`, `delivery_status`, `feishu_record_id`, `notes`

## API验证结果（2026-03-12）
| 查询 | HTTP | 数据 |
|------|------|------|
| orders (wechat_id, amount, order_stage, product) | 200 | 772 won + 188 deposit |
| contacts (active, non-deleted) | 200 | 9,882 条 |
| contacts (has_quote=true) | 200 | 1,331 条 |
| daily_tasks (today) | 200 | 3,378 条 |
| RPC dashboard_coverage | 500 | 超时(57014) → fallback生效 |
| RPC dashboard_funnel_conversations | 200 | 正常 |
| RPC dashboard_last_messages | 200 | 正常 |

## 数据分布说明
- 30天内新增联系人: 0条（所有contacts.add_time都早于30天前）
  - 影响: 漏斗"按获客"视角在30天范围内显示added=0（全零）
  - 解决: 用户切换到更长时间范围可看到数据
- 30天内订单: 32条
- 总订单金额(won): ~870万元

## 已知限制
1. **dashboard_coverage RPC超时**: chat_messages全表扫描导致，已有fallback（用contacts总数代替）。需优化SQL或加索引。见PQ-008。
2. **Sales breakdown不可用**: orders.sales_id是UUID，无法映射到SALES_LIST的wechatId。需要sales_id→wechat_id的映射表。
3. **Vercel未连接Git**: 每次更新需手动`vercel deploy --prod`，不会自动部署。
