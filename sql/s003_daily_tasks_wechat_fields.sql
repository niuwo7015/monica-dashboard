-- ==========================================
-- S-003: daily_tasks表新增wechat_id关联字段
-- PQ-003决策: 用wechat_id作为关联键，不依赖customer_id
-- PQ-004决策: 增加contact_wechat_id和sales_wechat_id字段
-- ==========================================

-- 1. 新增 contact_wechat_id（客户微信号，关联键）
ALTER TABLE daily_tasks ADD COLUMN IF NOT EXISTS contact_wechat_id text;

-- 2. 新增 sales_wechat_id（销售微信号，关联键）
ALTER TABLE daily_tasks ADD COLUMN IF NOT EXISTS sales_wechat_id text;

-- 3. 索引：按日期+销售微信号查询（替代原来的date+sales_id索引场景）
CREATE INDEX IF NOT EXISTS idx_daily_tasks_date_sales_wechat
ON daily_tasks(task_date, sales_wechat_id);

-- 4. 唯一约束：同一天同一客户不重复生成同类任务
CREATE UNIQUE INDEX IF NOT EXISTS idx_daily_tasks_unique_task
ON daily_tasks(task_date, contact_wechat_id, sales_wechat_id, task_type);
