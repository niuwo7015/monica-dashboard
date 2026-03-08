-- S-006: 订单表（飞书在线表格同步）
-- 执行时间：2026-03-08
-- 用途：存储从飞书订单表同步的成交数据，用于区分已成交/未成交客户

-- 创建 orders 表
CREATE TABLE IF NOT EXISTS orders (
    id              UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    customer_wechat_id  TEXT NOT NULL,           -- 客户微信号（关联contacts.wechat_id）
    sales_wechat_id     TEXT,                    -- 销售微信号
    order_date          DATE NOT NULL,           -- 下单日期
    amount              NUMERIC(12, 2),          -- 订单金额（元）
    product_line        TEXT,                    -- 产品线（如：沙发、床、柜子）
    order_status        TEXT DEFAULT 'completed',-- 订单状态：completed, cancelled, refunded
    feishu_row_id       TEXT,                    -- 飞书表格行ID（用于去重）
    remark              TEXT,                    -- 备注
    synced_at           TIMESTAMPTZ DEFAULT NOW(),-- 同步时间
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- 唯一约束：同一客户+同一日期+同一产品线 视为同一订单
-- 如果飞书有行ID，优先用 feishu_row_id 去重
CREATE UNIQUE INDEX IF NOT EXISTS idx_orders_feishu_row
    ON orders (feishu_row_id) WHERE feishu_row_id IS NOT NULL;

-- 查询索引
CREATE INDEX IF NOT EXISTS idx_orders_customer_wechat
    ON orders (customer_wechat_id);

CREATE INDEX IF NOT EXISTS idx_orders_sales_wechat
    ON orders (sales_wechat_id);

CREATE INDEX IF NOT EXISTS idx_orders_date
    ON orders (order_date);

-- RLS（如需前端直连可启用）
-- ALTER TABLE orders ENABLE ROW LEVEL SECURITY;

COMMENT ON TABLE orders IS '订单数据（从飞书在线表格同步）';
COMMENT ON COLUMN orders.customer_wechat_id IS '客户微信号，关联contacts.wechat_id';
COMMENT ON COLUMN orders.feishu_row_id IS '飞书表格行ID，用于upsert去重';
