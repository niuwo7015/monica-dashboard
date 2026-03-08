-- S-005: 添加earliest_message_at字段 + 聚合更新函数
-- 用途：标记每个联系人的最早消息时间，用于判断聊天记录是否完整
-- 执行方式：在Supabase Dashboard SQL Editor中运行

-- 1. 添加字段
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS earliest_message_at timestamp;

-- 2. 创建更新函数（可重复调用）
CREATE OR REPLACE FUNCTION update_contacts_earliest_message()
RETURNS TABLE(updated_count bigint) AS $$
  WITH mins AS (
    SELECT wechat_id, MIN(sent_at) as earliest
    FROM chat_messages
    WHERE room_id IS NULL AND sent_at IS NOT NULL
    GROUP BY wechat_id
  ),
  updated AS (
    UPDATE contacts c
    SET earliest_message_at = m.earliest,
        updated_at = now()
    FROM mins m
    WHERE c.wechat_id = m.wechat_id
    RETURNING c.id
  )
  SELECT count(*)::bigint as updated_count FROM updated;
$$ LANGUAGE sql;

-- 3. 创建查询完整记录客户的视图
-- earliest_message_at < '2025-10-01' 的客户聊天记录被视为"完整"
CREATE OR REPLACE VIEW contacts_with_complete_records AS
SELECT
  c.*,
  CASE
    WHEN c.earliest_message_at < '2025-10-01'::timestamp THEN true
    ELSE false
  END AS has_complete_records
FROM contacts c
WHERE c.friend_type != 2;  -- 排除群聊

-- 用法示例：
-- SELECT * FROM contacts_with_complete_records WHERE has_complete_records = true;
-- 或直接调用函数更新：SELECT * FROM update_contacts_earliest_message();
