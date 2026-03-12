-- T-027: Dashboard数据修复 — 新增RPC函数
-- 修复: P0 limit(1000)截断, P1 风险信号500截断, P2 报价匹配不准, P2 orders映射
-- 需要在 Supabase SQL Editor 中执行
-- 日期: 2026-03-13

-- ═══ 辅助索引 ═══

CREATE INDEX IF NOT EXISTS idx_chat_messages_sender_wechat
  ON chat_messages(wechat_id, sender_type)
  WHERE is_system_msg = false;

-- 支持LATERAL查最后一条消息（risk_top10用）
CREATE INDEX IF NOT EXISTS idx_chat_messages_wechat_sent
  ON chat_messages(wechat_id, sent_at DESC)
  WHERE is_system_msg = false;

-- 支持funnel_period按时间范围查对话
CREATE INDEX IF NOT EXISTS idx_chat_messages_wechat_sent_sender
  ON chat_messages(wechat_id, sent_at)
  WHERE is_system_msg = false AND sender_type = 'customer';

-- ═══ 1. 漏斗-按获客 (cohort) ═══
-- 基准池 = 选定时间内add_time的客户，追踪最终转化（不限时间）
-- 替代前端 limit(1000) 截断查询，改用服务端 COUNT + EXISTS

CREATE OR REPLACE FUNCTION dashboard_funnel_cohort(
  p_sales_ids text[],
  p_start date,
  p_end date
) RETURNS jsonb
LANGUAGE sql STABLE
SET statement_timeout = '30s'
AS $$
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
LANGUAGE sql STABLE
SET statement_timeout = '30s'
AS $$
  -- 从消息/订单侧出发，用时间范围先缩小扫描量，再反查contacts归属
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
      WHERE cm.sender_type = 'customer'
        AND cm.is_system_msg = false
        AND cm.sent_at >= p_start::timestamp
        AND cm.sent_at < (p_end + 1)::timestamp
        AND EXISTS (
          SELECT 1 FROM contacts c
          WHERE c.wechat_id = cm.wechat_id
            AND c.sales_wechat_id = ANY(p_sales_ids)
            AND c.is_deleted = 0 AND c.friend_type = 1
        )
    ),
    'quote', (
      SELECT COUNT(DISTINCT cm.wechat_id)
      FROM chat_messages cm
      WHERE cm.sender_type = 'sales'
        AND cm.is_system_msg = false
        AND cm.sent_at >= p_start::timestamp
        AND cm.sent_at < (p_end + 1)::timestamp
        AND (cm.content ~ '\d[\d,.]*\s*[万亿]?元' OR cm.content ~ '报价')
        AND EXISTS (
          SELECT 1 FROM contacts c
          WHERE c.wechat_id = cm.wechat_id
            AND c.sales_wechat_id = ANY(p_sales_ids)
            AND c.is_deleted = 0 AND c.friend_type = 1
        )
    ),
    'deposit', (
      SELECT COUNT(DISTINCT o.wechat_id)
      FROM orders o
      WHERE o.order_stage = 'deposit'
        AND o.order_date >= p_start AND o.order_date <= p_end
        AND EXISTS (
          SELECT 1 FROM contacts c
          WHERE c.wechat_id = o.wechat_id
            AND c.sales_wechat_id = ANY(p_sales_ids)
            AND c.is_deleted = 0 AND c.friend_type = 1
        )
    ),
    'won', (
      SELECT COUNT(DISTINCT o.wechat_id)
      FROM orders o
      WHERE o.order_stage = 'won'
        AND o.order_date >= p_start AND o.order_date <= p_end
        AND EXISTS (
          SELECT 1 FROM contacts c
          WHERE c.wechat_id = o.wechat_id
            AND c.sales_wechat_id = ANY(p_sales_ids)
            AND c.is_deleted = 0 AND c.friend_type = 1
        )
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
LANGUAGE sql STABLE
SET statement_timeout = '30s'
AS $$
  -- 优化: 先排除近7天有消息的联系人，再只对沉默联系人做LATERAL
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
  -- 找出近7天有任何消息的联系人（快速排除，利用sent_at索引）
  recently_active AS (
    SELECT DISTINCT cm.wechat_id
    FROM chat_messages cm
    WHERE cm.sent_at > NOW() - INTERVAL '7 days'
      AND cm.is_system_msg = false
      AND EXISTS (SELECT 1 FROM active a WHERE a.wechat_id = cm.wechat_id)
  ),
  -- 沉默候选人 = 活跃联系人 - 近7天有消息的
  candidates AS (
    SELECT a.* FROM active a
    WHERE NOT EXISTS (SELECT 1 FROM recently_active ra WHERE ra.wechat_id = a.wechat_id)
  ),
  -- 只保留曾经有过聊天记录的联系人（排除僵尸联系人）
  with_last_msg AS (
    SELECT
      cd.wechat_id, cd.nickname, cd.remark, cd.sales_wechat_id,
      lm.content AS last_content,
      lm.sent_at AS last_sent_at,
      EXTRACT(DAY FROM NOW() - lm.sent_at)::int AS silence_days
    FROM candidates cd
    INNER JOIN LATERAL (
      SELECT cm.content, cm.sent_at
      FROM chat_messages cm
      WHERE cm.wechat_id = cd.wechat_id
        AND cm.is_system_msg = false
        AND (cm.room_id IS NULL OR cm.room_id NOT LIKE '%@chatroom%')
      ORDER BY cm.sent_at DESC
      LIMIT 1
    ) lm ON true
  )
  SELECT
    t.wechat_id, t.nickname, t.remark, t.sales_wechat_id,
    t.silence_days, t.last_content, t.last_sent_at,
    (SELECT dt.status FROM daily_tasks dt
     WHERE dt.contact_wechat_id = t.wechat_id
     ORDER BY dt.task_date DESC LIMIT 1
    ) AS task_status
  FROM with_last_msg t
  ORDER BY t.silence_days DESC
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
