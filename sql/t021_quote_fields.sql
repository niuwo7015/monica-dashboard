-- T-021: Add quote tracking fields to contacts table
-- has_quote: whether this contact has received a price quote from sales
-- first_quote_at: timestamp of the earliest quote message

ALTER TABLE contacts ADD COLUMN IF NOT EXISTS has_quote BOOLEAN DEFAULT false;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS first_quote_at TIMESTAMPTZ;
