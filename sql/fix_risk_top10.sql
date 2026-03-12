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
  recently_active AS (
    SELECT DISTINCT cm.wechat_id
    FROM chat_messages cm
    WHERE cm.sent_at > NOW() - INTERVAL '7 days'
      AND cm.is_system_msg = false
      AND EXISTS (SELECT 1 FROM active a WHERE a.wechat_id = cm.wechat_id)
  ),
  candidates AS (
    SELECT a.* FROM active a
    WHERE NOT EXISTS (SELECT 1 FROM recently_active ra WHERE ra.wechat_id = a.wechat_id)
  ),
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
