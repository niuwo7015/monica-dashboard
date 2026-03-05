-- ==========================================
-- Phase 0 表结构变更
-- ==========================================

-- 1. chat_messages表新增字段
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS file_url text;
ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS msg_svr_id text;

CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_messages_msg_svr_id
ON chat_messages(msg_svr_id) WHERE msg_svr_id IS NOT NULL;

-- 2. 新建daily_tasks表
CREATE TABLE IF NOT EXISTS daily_tasks (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  customer_id uuid REFERENCES customers(id),
  sales_id uuid REFERENCES users(id),
  task_date date NOT NULL,
  task_type text NOT NULL,
  trigger_rule text,
  priority int DEFAULT 0,
  status text DEFAULT 'pending',
  executed_at timestamp,
  customer_responded boolean,
  created_at timestamp DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_daily_tasks_date_sales ON daily_tasks(task_date, sales_id);

-- 3. customers表新增字段
ALTER TABLE customers ADD COLUMN IF NOT EXISTS renovation_stage text;
ALTER TABLE customers ADD COLUMN IF NOT EXISTS estimated_purchase_timeline text;

-- 4. 新建api_call_logs表
CREATE TABLE IF NOT EXISTS api_call_logs (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  call_type text NOT NULL,
  model text NOT NULL,
  customer_id uuid,
  input_prompt text,
  output_response text,
  input_tokens int,
  output_tokens int,
  cost_usd numeric(10,6),
  created_at timestamp DEFAULT now()
);

-- 5. 新建contacts表（云客好友列表1:1映射）
CREATE TABLE IF NOT EXISTS contacts (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  wechat_id text NOT NULL,
  wechat_alias text,
  nickname text,
  remark text,
  friend_type int DEFAULT 1,
  from_type text,
  head_url text,
  phone text,
  description text,
  gender int DEFAULT 0,
  region text,
  yunke_create_time timestamp,
  add_time timestamp,
  sales_wechat_id text,
  is_deleted int DEFAULT 0,
  yunke_update_time timestamp,
  contact_tag text DEFAULT '未分类',
  customer_id uuid REFERENCES customers(id),
  created_at timestamp DEFAULT now(),
  updated_at timestamp DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_wechat_id_sales
ON contacts(wechat_id, sales_wechat_id);

-- 6. 新建group_customer_mapping表（群聊与客户关联，先建空表）
CREATE TABLE IF NOT EXISTS group_customer_mapping (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  group_wechat_id text NOT NULL,
  group_name text,
  customer_wechat_id text,
  customer_id uuid REFERENCES customers(id),
  sales_wechat_id text,
  created_at timestamp DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_group_mapping
ON group_customer_mapping(group_wechat_id, customer_wechat_id)
WHERE customer_wechat_id IS NOT NULL;
