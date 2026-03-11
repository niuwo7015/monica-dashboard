# T-025: 管理层数据看板更新 — 执行报告

**日期**: 2026-03-12
**任务代号**: T-025
**状态**: 已完成，已推送到main触发Vercel部署

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
  - 有对话: chat_messages在范围内的distinct客户（排除is_system_msg）
  - 已报价: 有对话的客户中has_quote=true
  - 付定金: orders中product_line含"订金/意向金"或amount=1000
  - 成交: orders中amount>1000
- toggle样式沿用FilterBar的pill风格（rgba(232,196,124,0.15)选中态）

### 3. 漏斗总转化率
- 漏斗区块右上角显示大字总转化率（加微信→成交）
- 每层右侧新增两列指标:
  - ↓ xx%: 层间转化率（该层/上一层）
  - xx%: 总转化率（该层/第一层），颜色 rgba(255,255,255,0.2)

### 4. 沉默预警Top10
- 从5条扩展到10条
- 数据源: chat_messages直接查询最后互动时间（排除is_system_msg=true）
- 排除: 已成交客户（orders表amount>1000），销售微信号
- 颜色阈值: >60天 #E85D5D, >30天 #E8C47C, 其他 rgba(255,255,255,0.4)
- 标题改为"沉默预警 · Top10"

### 5. 沉默预警WoW对比
- 卡片右上角显示: 本周新增沉默>14天 vs 上周同口径
- 本周 = 最后消息14-20天前（近7天跨过14天阈值的客户）
- 上周 = 最后消息21-27天前
- 本周>上周红色，反之绿色

### 6. 真实数据接入
- 覆盖率: daily_tasks表，今日done vs pending + RPC dashboard_coverage
- 漏斗: contacts + chat_messages + orders联查（双模式）
- 业绩: orders表按order_date筛选，deposit/won用product_line+amount判断
- 销售跟进: daily_tasks按sales_wechat_id分组
- 风险信号: chat_messages + RPC dashboard_last_messages
- 销售名映射: SALES_LIST from theme.js

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
- Git commit: edea1ac
- 已push到main分支，Vercel自动部署
- 访问地址: https://monica-crm-eta.vercel.app/dashboard

## 待确认事项
- Supabase RPC函数（dashboard_coverage, dashboard_funnel_conversations, dashboard_last_messages）是否已部署
  - 未部署时自动fallback到直接查询，功能不受影响
- orders表product_line字段是否包含"订金/意向金"关键词
  - 如果product_line不含这些关键词，付定金层仅靠amount=1000判断
