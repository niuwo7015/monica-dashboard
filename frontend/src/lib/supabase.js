import { createClient } from '@supabase/supabase-js'

const supabaseUrl = 'https://dieeejjzbhkpgxdhwlxf.supabase.co'
const supabaseAnonKey = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRpZWVlamp6YmhrcGd4ZGh3bHhmIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzIyOTg0MjcsImV4cCI6MjA4Nzg3NDQyN30.SfdDLKKGxg-FmISuK36XJ6mmpHeUNoSbcOwBrTroOpc'

export const supabase = createClient(supabaseUrl, supabaseAnonKey)
