# T-027: Dashboard数据修复 — 执行报告

**日期**: 2026-03-13
**任务代号**: T-027
**状态**: 代码已完成，SQL待部署

---

## 修复清单

### P0-1: limit(1000) 截断导致漏斗数据严重偏低

**根因**: 漏斗查询用 `.limit(1000)` 获取消息再在JS端去重取distinct wechat_id。每200人chunk的消息量轻松超过1000条，导致大量客户被漏计。

**修复**:
- 新增 `dashboard_funnel_cohort(p_sales_ids, p_start, p_end)` RPC — 按获客模式，服务端 COUNT + EXISTS
- 新增 `dashboard_funnel_period(p_sales_ids, p_start, p_end)` RPC — 按成交模式，服务端 COUNT(DISTINCT)
- JS端 RPC优先，fallback将limit从1000提升到50000
- 同时修复了原 `dashboard_funnel_conversations` RPC的误用（它不按sales_id过滤）

### P0-2: 漏斗"按获客"默认30天全零

**根因**: 所有contacts.add_time早于30天前，默认30天视角下 added=0，整个漏斗全零。

**修复**:
- TIME_PRESETS 新增: 90天、半年、全部
- computeDateRange 新增对应处理（'all' 从 2024-01-01 起）
- FunnelCard 在按获客模式下added=0时显示提示: "该时间段无新增客户，试试选择「半年」或「全部」"

### P1: 风险信号只查前500个客户

**根因**: `contactIds.slice(0, 500)` 硬截断，9882个活跃客户中95%未被检查。

**修复**:
- 新增 `dashboard_risk_top10(p_sales_ids)` RPC — 在DB端完成:
  - 排除已成交客户和销售自己的微信号
  - DISTINCT ON 取每个客户最后一条消息
  - 计算沉默天数，过滤≥7天
  - ORDER BY silence_days DESC LIMIT 10
- JS端 RPC优先，fallback保留原500限制逻辑

### P2-1: "已报价"匹配虚高

**根因**: `content.ilike.%元%` 匹配到元旦、元素、单元等非价格场景。

**修复**:
- RPC内改用精确正则: `content ~ '\d[\d,.]*\s*[万亿]?元' OR content ~ '报价'`
  - 要求"元"前面有数字（如"5000元"、"3.8万元"）
  - "报价"保留（业务场景足够精确）
  - 删除"价格"匹配（太宽泛）
- JS fallback简化为仅匹配 `%报价%`

### P2-2: orders通过contacts映射丢数据

**根因**:
1. orders无sales_wechat_id字段，需通过contacts.wechat_id映射
2. 映射时过滤了is_deleted=0，已删除客户的订单丢失
3. 部分orders的wechat_id实际是wechat_alias，无法匹配

**修复（JS端，立即生效）**:
- contacts映射查询去掉 is_deleted 和 friend_type 过滤
- 映射表同时建立 wechat_id 和 wechat_alias 的映射
- 订单优先用 orders.sales_wechat_id（SQL迁移后），fallback用contacts映射

**修复（SQL端，需部署）**:
- ALTER TABLE orders ADD COLUMN sales_wechat_id TEXT
- 从contacts回填（直接匹配 + wechat_alias匹配）
- 建索引 idx_orders_sales_wechat_id

---

## 修改文件

| 文件 | 变更 |
|------|------|
| `sql/t027_dashboard_fixes.sql` | 新增：3个RPC函数 + orders表迁移 |
| `frontend/src/lib/dashboardQueries.js` | 重构：RPC优先 + 时间预设 + 映射扩大 |
| `frontend/src/pages/Dashboard.jsx` | 漏斗空数据提示 |

## 部署步骤

1. **SQL先行**（在Supabase SQL Editor执行）:
   ```
   sql/t027_dashboard_fixes.sql
   ```
   包含：索引、3个RPC函数、orders表schema变更+数据回填

2. **前端部署**:
   ```bash
   cd frontend && vercel deploy --prod
   ```

3. **验证**: 访问 dashboard，分别测试:
   - 30天视角：覆盖率、业绩、销售跟进应有数据
   - 半年/全部视角：漏斗按获客应有数据
   - 风险信号：应显示真正的Top10沉默客户

## 注意事项

- SQL未执行前，前端会自动fallback到原逻辑（limit提升到50000，比原来的1000好很多）
- orders.sales_wechat_id列添加前，JS端已通过扩大contacts映射覆盖大部分丢失数据
- RPC函数都GRANT了anon权限，前端anon key可直接调用
