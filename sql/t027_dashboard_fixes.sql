-- T-027: Dashboard数据修复 — 新增RPC函数
-- 修复: P0 limit(1000)截断, P1 风险信号500截断, P2 报价匹配不准, P2 orders映射
-- 需要在 Supabase SQL Editor 中执行
-- 日期: 2026-03-13

-- ═══ 辅助索引 ═══

CREATE INDEX IF NOT EXISTS idx_chat_messages_sender_wechat
  ON chat_messages(wechat_id, sender_type)
  WHERE is_system_msg = false;

-- ═══ 1. 漏斗-按获客 (cohort) ═══
-- 基准池 = 选定时间内add_time的客户，追踪最终转化（不限时间）
-- 替代前端 limit(1000) 截断查询，改用服务端 COUNT + EXISTS

CREATE OR REPLACE FUNCTION dashboard_funnel_cohort(
  p_sales_ids text[],
  p_start date,
  p_end date
) RETURNS jsonb
LANGUAGE sql STABLE AS $$
  WITH cohort AS (
    SELECT wechat_id FROM contacts
    WHERE sales_wechat_id = ANY(p_sales_ids)
      AND is_deleted = 0 AND friend_type = 1
      AND add_time >= p_start::timestamp
      AND add_time < (p_end + 1)::timestamp
  )
  SELECT jsonb_build_object(
    'added', (SELECT COUNT(*) FROM cohort),
    'conversation', (
      SELECT COUNT(*) FROM cohort c WHERE EXISTS (
        SELECT 1 FROM chat_messages cm
        WHERE cm.wechat_id = c.wechat_id
          AND cm.sender_type = 'customer'
          AND cm.is_system_msg = false
      )
    ),
    'quote', (
      SELECT COUNT(*) FROM cohort c WHERE EXISTS (
        SELECT 1 FROM chat_messages cm
        WHERE cm.wechat_id = c.wechat_id
          AND cm.sender_type = 'sales'
          AND cm.is_system_msg = false
          AND (cm.content ~ '\d[\d,.]*\s*[万亿]?元' OR cm.content ~ '报价')
      )
    ),
    'deposit', (
      SELECT COUNT(*) FROM cohort c WHERE EXISTS (
        SELECT 1 FROM orders o
        WHERE o.wechat_id = c.wechat_id AND o.order_stage = 'deposit'
      )
    ),
    'won', (
      SELECT COUNT(*) FROM cohort c WHERE EXISTS (
        SELECT 1 FROM orders o
        WHERE o.wechat_id = c.wechat_id AND o.order_stage = 'won'
      )
    )
  )
$$;

GRANT EXECUTE ON FUNCTION dashboard_funnel_cohort(text[], date, date) TO anon;

-- ═══ 2. 漏斗-按成交 (period) ═══
-- 每层只算选定时间内发生的动作
-- 替代前端多个截断查询，一次RPC返回全部5层

CREATE OR REPLACE FUNCTION dashboard_funnel_period(
  p_sales_ids text[],
  p_start date,
  p_end date
) RETURNS jsonb
LANGUAGE sql STABLE AS $$
  WITH core_contacts AS (
    SELECT wechat_id FROM contacts
    WHERE sales_wechat_id = ANY(p_sales_ids)
      AND is_deleted = 0 AND friend_type = 1
  )
  SELECT jsonb_build_object(
    'added', (
      SELECT COUNT(*) FROM contacts
      WHERE sales_wechat_id = ANY(p_sales_ids)
        AND is_deleted = 0 AND friend_type = 1
        AND add_time >= p_start::timestamp
        AND add_time < (p_end + 1)::timestamp
    ),
    'conversation', (
      SELECT COUNT(DISTINCT cm.wechat_id)
      FROM chat_messages cm
      INNER JOIN core_contacts cc ON cc.wechat_id = cm.wechat_id
      WHERE cm.sender_type = 'customer'
        AND cm.is_system_msg = false
        AND cm.sent_at >= p_start::timestamp
        AND cm.sent_at < (p_end + 1)::timestamp
    ),
    'quote', (
      SELECT COUNT(DISTINCT cm.wechat_id)
      FROM chat_messages cm
      INNER JOIN core_contacts cc ON cc.wechat_id = cm.wechat_id
      WHERE cm.sender_type = 'sales'
        AND cm.is_system_msg = false
        AND cm.sent_at >= p_start::timestamp
        AND cm.sent_at < (p_end + 1)::timestamp
        AND (cm.content ~ '\d[\d,.]*\s*[万亿]?元' OR cm.content ~ '报价')
    ),
    'deposit', (
      SELECT COUNT(DISTINCT o.wechat_id)
      FROM orders o
      INNER JOIN core_contacts cc ON cc.wechat_id = o.wechat_id
      WHERE o.order_stage = 'deposit'
        AND o.order_date >= p_start AND o.order_date <= p_end
    ),
    'won', (
      SELECT COUNT(DISTINCT o.wechat_id)
      FROM orders o
      INNER JOIN core_contacts cc ON cc.wechat_id = o.wechat_id
      WHERE o.order_stage = 'won'
        AND o.order_date >= p_start AND o.order_date <= p_end
    )
  )
$$;

GRANT EXECUTE ON FUNCTION dashboard_funnel_period(text[], date, date) TO anon;

-- ═══ 3. 风险信号 Top 10 ═══
-- 替代前端 slice(0,500) 截断，直接在DB端排序取Top10
-- 覆盖全部9000+活跃联系人

CREATE OR REPLACE FUNCTION dashboard_risk_top10(p_sales_ids text[])
RETURNS TABLE(
  wechat_id text,
  nickname text,
  remark text,
  sales_wechat_id text,
  silence_days int,
  last_content text,
  last_sent_at timestamptz,
  task_status text
)
LANGUAGE sql STABLE AS $$
  WITH active AS (
    SELECT c.wechat_id, c.nickname, c.remark, c.sales_wechat_id
    FROM contacts c
    WHERE c.sales_wechat_id = ANY(p_sales_ids)
      AND c.is_deleted = 0 AND c.friend_type = 1
      AND c.wechat_id != ALL(p_sales_ids)
      AND NOT EXISTS (
        SELECT 1 FROM orders o
        WHERE o.wechat_id = c.wechat_id AND o.order_stage = 'won'
      )
  ),
  last_msg AS (
    SELECT DISTINCT ON (cm.wechat_id)
      cm.wechat_id, cm.content, cm.sent_at
    FROM chat_messages cm
    INNER JOIN active a ON a.wechat_id = cm.wechat_id
    WHERE cm.is_system_msg = false
      AND (cm.room_id IS NULL OR cm.room_id NOT LIKE '%@chatroom%')
    ORDER BY cm.wechat_id, cm.sent_at DESC
  ),
  last_task AS (
    SELECT DISTINCT ON (dt.contact_wechat_id)
      dt.contact_wechat_id, dt.status
    FROM daily_tasks dt
    INNER JOIN active a ON a.wechat_id = dt.contact_wechat_id
    ORDER BY dt.contact_wechat_id, dt.task_date DESC
  )
  SELECT
    a.wechat_id,
    a.nickname,
    a.remark,
    a.sales_wechat_id,
    COALESCE(EXTRACT(DAY FROM NOW() - lm.sent_at)::int, 999) AS silence_days,
    lm.content AS last_content,
    lm.sent_at AS last_sent_at,
    lt.status AS task_status
  FROM active a
  LEFT JOIN last_msg lm ON lm.wechat_id = a.wechat_id
  LEFT JOIN last_task lt ON lt.contact_wechat_id = a.wechat_id
  WHERE COALESCE(EXTRACT(DAY FROM NOW() - lm.sent_at)::int, 999) >= 7
  ORDER BY silence_days DESC
  LIMIT 10
$$;

GRANT EXECUTE ON FUNCTION dashboard_risk_top10(text[]) TO anon;

-- ═══ 4. orders表增加 sales_wechat_id ═══
-- 修复: orders通过contacts映射会丢失已删除客户和wechat_alias匹配的数据

ALTER TABLE orders ADD COLUMN IF NOT EXISTS sales_wechat_id TEXT;

-- 从contacts回填（直接wechat_id匹配）
UPDATE orders o
SET sales_wechat_id = c.sales_wechat_id
FROM contacts c
WHERE c.wechat_id = o.wechat_id
  AND c.sales_wechat_id IS NOT NULL
  AND o.sales_wechat_id IS NULL;

-- 从contacts回填（wechat_alias匹配）
UPDATE orders o
SET sales_wechat_id = c.sales_wechat_id
FROM contacts c
WHERE c.wechat_alias = o.wechat_id
  AND c.wechat_alias IS NOT NULL
  AND c.sales_wechat_id IS NOT NULL
  AND o.sales_wechat_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_orders_sales_wechat_id ON orders(sales_wechat_id);
