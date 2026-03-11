-- T-022: Dashboard RPC functions for frontend data queries
-- 执行时间：2026-03-12
-- 用途：为前端数据看板提供高效的聚合查询，避免大量数据传输到客户端
-- 注意：需要在 Supabase SQL Editor 中执行此文件

-- ═══ 索引（提升查询性能）═══

-- 覆盖率查询索引：按 wechat_id 过滤私聊非系统消息
CREATE INDEX IF NOT EXISTS idx_chat_messages_private_nonsys
  ON chat_messages(wechat_id, sender_type, sent_at)
  WHERE is_system_msg = false AND (room_id IS NULL OR room_id NOT LIKE '%@chatroom%');

-- ═══ 1. 跟进覆盖率 ═══
-- 返回: { total_active: int, followed_7d: int }
-- total_active = 有过至少1条私聊非系统消息的客户数
-- followed_7d  = 上述客户中，最近7天内有销售发消息的客户数

CREATE OR REPLACE FUNCTION dashboard_coverage()
RETURNS jsonb
LANGUAGE sql STABLE
AS $$
  WITH private_contacts AS (
    SELECT DISTINCT cm.wechat_id
    FROM chat_messages cm
    INNER JOIN contacts c ON c.wechat_id = cm.wechat_id AND c.is_deleted = 0 AND c.friend_type = 1
    WHERE cm.is_system_msg = false
      AND (cm.room_id IS NULL OR cm.room_id NOT LIKE '%@chatroom%')
  ),
  followed AS (
    SELECT DISTINCT cm.wechat_id
    FROM chat_messages cm
    INNER JOIN private_contacts pc ON pc.wechat_id = cm.wechat_id
    WHERE cm.sender_type = 'sales'
      AND cm.is_system_msg = false
      AND (cm.room_id IS NULL OR cm.room_id NOT LIKE '%@chatroom%')
      AND cm.sent_at >= NOW() - INTERVAL '7 days'
  )
  SELECT jsonb_build_object(
    'total_active', (SELECT COUNT(*) FROM private_contacts),
    'followed_7d', (SELECT COUNT(*) FROM followed)
  )
$$;

-- 授权 anon 角色调用
GRANT EXECUTE ON FUNCTION dashboard_coverage() TO anon;

-- ═══ 2. 漏斗-有对话数 ═══
-- 给定时间范围内加微信的客户中，有过至少1条私聊非系统消息的数量
-- 参数: p_start date, p_end date (NULL = 不限)

CREATE OR REPLACE FUNCTION dashboard_funnel_conversations(
  p_start date DEFAULT NULL,
  p_end date DEFAULT NULL
)
RETURNS int
LANGUAGE sql STABLE
AS $$
  SELECT COUNT(DISTINCT c.wechat_id)::int
  FROM contacts c
  WHERE c.is_deleted = 0
    AND c.friend_type = 1
    AND (p_start IS NULL OR c.add_time >= p_start::timestamp)
    AND (p_end IS NULL OR c.add_time < (p_end + 1)::timestamp)
    AND EXISTS (
      SELECT 1 FROM chat_messages cm
      WHERE cm.wechat_id = c.wechat_id
        AND cm.is_system_msg = false
        AND (cm.room_id IS NULL OR cm.room_id NOT LIKE '%@chatroom%')
    )
$$;

GRANT EXECUTE ON FUNCTION dashboard_funnel_conversations(date, date) TO anon;

-- ═══ 3. 风险信号-最后消息 ═══
-- 批量获取多个客户的最后一条私聊非系统消息
-- 参数: p_wechat_ids text[] (客户微信号数组)

CREATE OR REPLACE FUNCTION dashboard_last_messages(p_wechat_ids text[])
RETURNS TABLE(wechat_id text, content text, sender_type text, sent_at timestamptz)
LANGUAGE sql STABLE
AS $$
  SELECT DISTINCT ON (cm.wechat_id)
    cm.wechat_id,
    COALESCE(cm.content, '[媒体消息]') as content,
    cm.sender_type,
    cm.sent_at
  FROM chat_messages cm
  WHERE cm.wechat_id = ANY(p_wechat_ids)
    AND cm.is_system_msg = false
    AND (cm.room_id IS NULL OR cm.room_id NOT LIKE '%@chatroom%')
  ORDER BY cm.wechat_id, cm.sent_at DESC
$$;

GRANT EXECUTE ON FUNCTION dashboard_last_messages(text[]) TO anon;
