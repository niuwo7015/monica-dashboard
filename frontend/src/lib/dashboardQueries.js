/* ═══════════════════════════════════════
   T-025: Dashboard Data Queries
   数据看板 Supabase 查询层
   ═══════════════════════════════════════ */

import { supabase } from './supabase'
import { SALES_LIST } from './theme'

// ─── Time Range Helpers ───

export const TIME_PRESETS = [
  { key: 'today', label: '今天' },
  { key: '7d', label: '7天' },
  { key: '14d', label: '14天' },
  { key: '30d', label: '30天' },
  { key: 'month', label: '本月' },
  { key: 'lastMonth', label: '上月' },
  { key: 'custom', label: '自定义' },
]

export function computeDateRange(preset, customStart, customEnd) {
  const today = new Date()
  today.setHours(0, 0, 0, 0)

  switch (preset) {
    case 'today':
      return { start: fmtDate(today), end: fmtDate(today) }
    case '7d':
      return { start: fmtDate(daysAgo(today, 6)), end: fmtDate(today) }
    case '14d':
      return { start: fmtDate(daysAgo(today, 13)), end: fmtDate(today) }
    case '30d':
      return { start: fmtDate(daysAgo(today, 29)), end: fmtDate(today) }
    case 'month': {
      const first = new Date(today.getFullYear(), today.getMonth(), 1)
      return { start: fmtDate(first), end: fmtDate(today) }
    }
    case 'lastMonth': {
      const first = new Date(today.getFullYear(), today.getMonth() - 1, 1)
      const last = new Date(today.getFullYear(), today.getMonth(), 0)
      return { start: fmtDate(first), end: fmtDate(last) }
    }
    case 'custom':
      return { start: customStart || null, end: customEnd || null }
    default:
      return { start: fmtDate(daysAgo(today, 29)), end: fmtDate(today) }
  }
}

function daysAgo(base, n) {
  const d = new Date(base)
  d.setDate(d.getDate() - n)
  return d
}

function fmtDate(d) {
  return d.toISOString().split('T')[0]
}

const SALES_IDS = new Set(SALES_LIST.map(s => s.wechatId))

// ─── 1. Coverage Stats ───

export async function fetchCoverageStats() {
  const today = fmtDate(new Date())

  const { data: tasks } = await supabase
    .from('daily_tasks')
    .select('id, status')
    .eq('task_date', today)

  const allTasks = tasks || []
  const tasksDone = allTasks.filter(t => t.status === 'done').length
  const tasksPending = allTasks.filter(t => t.status === 'pending').length

  let totalActive = 0, followed7d = 0, rpcAvailable = false
  try {
    const { data, error } = await supabase.rpc('dashboard_coverage')
    if (!error && data) {
      totalActive = data.total_active || 0
      followed7d = data.followed_7d || 0
      rpcAvailable = true
    }
  } catch (_) { /* RPC not deployed */ }

  if (!rpcAvailable) {
    // Fallback: count all active contacts (no earliest_message_at column)
    const { count: activeCount } = await supabase
      .from('contacts')
      .select('*', { count: 'exact', head: true })
      .eq('is_deleted', 0)
      .eq('friend_type', 1)

    totalActive = activeCount || 0
    followed7d = tasksDone
  }

  const coveragePct = totalActive > 0 ? Math.round((followed7d / totalActive) * 100) : 0

  return { coveragePct, totalActive, followed7d, tasksDone, tasksPending, rpcAvailable }
}

// ─── 2a. Funnel — 按获客 (cohort-based) ───
// 分母=选定时间内add_time的客户，追踪这批人最终走到哪一步

export async function fetchFunnelByAcquisition(dateRange) {
  const { start, end } = dateRange
  if (!start) return { added: 0, conversation: 0, quote: 0, deposit: 0, won: 0 }

  // Cohort: contacts added in range
  const { data: cohortData } = await supabase
    .from('contacts')
    .select('wechat_id')
    .eq('is_deleted', 0)
    .eq('friend_type', 1)
    .gte('add_time', start)
    .lte('add_time', end + 'T23:59:59')

  const cohortIds = (cohortData || []).map(c => c.wechat_id)
  const added = cohortIds.length
  if (added === 0) return { added: 0, conversation: 0, quote: 0, deposit: 0, won: 0 }

  // 有对话: cohort members with any non-system private messages (ever)
  let conversationCount = 0
  try {
    const { data, error } = await supabase.rpc('dashboard_funnel_conversations', {
      p_start: start, p_end: end,
    })
    if (!error && data !== null) conversationCount = data
  } catch (_) {
    // Fallback: count contacts in cohort with has_quote (rough proxy)
    const { count } = await supabase
      .from('contacts')
      .select('*', { count: 'exact', head: true })
      .in('wechat_id', cohortIds.slice(0, 500))
    conversationCount = count || 0
  }

  // 已报价: cohort members with has_quote = true (ever)
  let quoteCount = 0
  try {
    const { count, error } = await supabase
      .from('contacts')
      .select('*', { count: 'exact', head: true })
      .in('wechat_id', cohortIds.slice(0, 500))
      .eq('has_quote', true)
    if (!error) quoteCount = count || 0
  } catch (_) {}

  // 付定金: cohort members with order_stage = 'deposit' or 'won' (ever)
  let depositCount = 0
  try {
    const { data: depOrders } = await supabase
      .from('orders')
      .select('wechat_id')
      .in('wechat_id', cohortIds.slice(0, 500))
      .in('order_stage', ['deposit', 'won'])
    depositCount = new Set((depOrders || []).map(o => o.wechat_id)).size
  } catch (_) {}

  // 成交: cohort members with order_stage = 'won' (ever)
  let wonCount = 0
  try {
    const { data: wonOrders } = await supabase
      .from('orders')
      .select('wechat_id')
      .in('wechat_id', cohortIds.slice(0, 500))
      .eq('order_stage', 'won')
    wonCount = new Set((wonOrders || []).map(o => o.wechat_id)).size
  } catch (_) {}

  return { added, conversation: conversationCount, quote: quoteCount, deposit: depositCount, won: wonCount }
}

// ─── 2b. Funnel — 按成交 (period-based) ───
// 每层只算选定时间内发生的动作

export async function fetchFunnelByTransaction(dateRange) {
  const { start, end } = dateRange
  if (!start) return { added: 0, conversation: 0, quote: 0, deposit: 0, won: 0 }

  // 加微信: contacts.add_time in range
  const { count: addedCount } = await supabase
    .from('contacts')
    .select('*', { count: 'exact', head: true })
    .eq('is_deleted', 0)
    .eq('friend_type', 1)
    .gte('add_time', start)
    .lte('add_time', end + 'T23:59:59')

  // 有对话: use RPC for conversation count in date range
  let conversationCount = 0
  try {
    const { data, error } = await supabase.rpc('dashboard_funnel_conversations', {
      p_start: start, p_end: end,
    })
    if (!error && data !== null) conversationCount = data
  } catch (_) {}

  // 已报价: contacts with has_quote = true AND added in range (rough proxy)
  let quoteCount = 0
  try {
    const { count, error } = await supabase
      .from('contacts')
      .select('*', { count: 'exact', head: true })
      .eq('is_deleted', 0)
      .eq('friend_type', 1)
      .eq('has_quote', true)
      .gte('add_time', start)
      .lte('add_time', end + 'T23:59:59')
    if (!error) quoteCount = count || 0
  } catch (_) {}

  // 付定金: orders in range with order_stage in ('deposit','won')
  let depositCount = 0
  try {
    const { data: depOrders } = await supabase
      .from('orders')
      .select('wechat_id')
      .gte('order_date', start)
      .lte('order_date', end)
      .in('order_stage', ['deposit', 'won'])
    depositCount = new Set((depOrders || []).map(o => o.wechat_id)).size
  } catch (_) {}

  // 成交: orders in range with order_stage = 'won'
  let wonCount = 0
  try {
    const { data: wonOrders } = await supabase
      .from('orders')
      .select('wechat_id')
      .gte('order_date', start)
      .lte('order_date', end)
      .eq('order_stage', 'won')
    wonCount = new Set((wonOrders || []).map(o => o.wechat_id)).size
  } catch (_) {}

  return {
    added: addedCount || 0,
    conversation: conversationCount,
    quote: quoteCount,
    deposit: depositCount,
    won: wonCount,
  }
}

// ─── 3. Performance Stats ───
// Actual orders columns: wechat_id, sales_id(uuid), product, amount, deposit, balance, order_stage, order_date

export async function fetchPerformanceStats(dateRange) {
  const { start, end } = dateRange

  let query = supabase
    .from('orders')
    .select('amount, deposit, wechat_id, order_date, order_stage, product')

  if (start) query = query.gte('order_date', start)
  if (end) query = query.lte('order_date', end)

  const { data: orders, error } = await query

  let orderList = orders || []
  if (error) {
    // If orders table is inaccessible, return empty
    return { totalAmount: 0, totalOrders: 0, salesBreakdown: [], depositToWonRate: null }
  }

  const totalAmount = orderList.reduce((sum, o) => sum + (parseFloat(o.amount) || 0), 0)
  const totalOrders = orderList.length

  // Per-sales breakdown: since orders.sales_id is UUID not wechat_id,
  // we can't map to SALES_LIST directly. Skip per-sales breakdown for now.
  const salesBreakdown = []

  // Deposit → Won conversion using order_stage
  const depositCustomers = new Set(
    orderList.filter(o => o.order_stage === 'deposit').map(o => o.wechat_id)
  )
  const wonCustomers = new Set(
    orderList.filter(o => o.order_stage === 'won').map(o => o.wechat_id)
  )
  // Customers who had deposit stage AND also have won stage
  const convertedCount = [...depositCustomers].filter(c => wonCustomers.has(c)).length
  const depositToWonRate = depositCustomers.size > 0
    ? Math.round((convertedCount / depositCustomers.size) * 100)
    : null

  return { totalAmount, totalOrders, salesBreakdown, depositToWonRate }
}

// ─── 4. Sales Follow-up (today) ───

export async function fetchSalesFollowUp() {
  const today = fmtDate(new Date())

  const { data: tasks } = await supabase
    .from('daily_tasks')
    .select('sales_wechat_id, status')
    .eq('task_date', today)

  const salesMap = {}
  SALES_LIST.forEach(s => {
    salesMap[s.wechatId] = { name: s.name, wechatId: s.wechatId, done: 0, pending: 0, total: 0 }
  })

  ;(tasks || []).forEach(t => {
    if (salesMap[t.sales_wechat_id]) {
      salesMap[t.sales_wechat_id].total++
      if (t.status === 'done') salesMap[t.sales_wechat_id].done++
      else salesMap[t.sales_wechat_id].pending++
    }
  })

  return Object.values(salesMap).filter(s => s.total > 0)
}

// ─── 5. Risk Signals + Silence WoW ───
// 数据源: chat_messages 算最后互动时间 (via RPC)
// 排除: 已成交客户 (order_stage = 'won'), 销售微信号

export async function fetchRiskAndSilence() {
  // Get won customer wechat_ids from orders
  let wonCustomerIds = new Set()
  try {
    const { data: wonOrders } = await supabase
      .from('orders')
      .select('wechat_id')
      .eq('order_stage', 'won')
    ;(wonOrders || []).forEach(o => wonCustomerIds.add(o.wechat_id))
  } catch (_) {}

  // Get all active contacts (no earliest_message_at filter - column doesn't exist)
  const { data: contacts } = await supabase
    .from('contacts')
    .select('wechat_id, nickname, remark, contact_tag, sales_wechat_id')
    .eq('is_deleted', 0)
    .eq('friend_type', 1)

  // Exclude won customers and sales wechat IDs
  const eligible = (contacts || []).filter(c =>
    !wonCustomerIds.has(c.wechat_id) && !SALES_IDS.has(c.wechat_id)
  )

  if (eligible.length === 0) {
    return { riskSignals: [], silenceThisWeek: 0, silenceLastWeek: 0 }
  }

  // For risk signals, we need last message time. Use RPC if available.
  // Only check a subset to avoid huge queries - get contacts with has_quote first
  // (they're higher value and more likely to have conversations)
  const { data: quotedContacts } = await supabase
    .from('contacts')
    .select('wechat_id')
    .eq('is_deleted', 0)
    .eq('friend_type', 1)
    .eq('has_quote', true)

  const quotedIds = new Set((quotedContacts || []).map(c => c.wechat_id))
  // Prioritize quoted contacts for risk signals
  const priorityEligible = eligible.filter(c => quotedIds.has(c.wechat_id))
  const checkList = priorityEligible.length > 0 ? priorityEligible : eligible.slice(0, 500)

  const contactIds = checkList.map(c => c.wechat_id)
  const contactMap = {}
  checkList.forEach(c => { contactMap[c.wechat_id] = c })

  // Get last non-system private message per contact via RPC
  let msgMap = {}
  try {
    const { data: msgs, error } = await supabase.rpc('dashboard_last_messages', {
      p_wechat_ids: contactIds.slice(0, 500),
    })
    if (!error && msgs) {
      msgs.forEach(m => { msgMap[m.wechat_id] = m })
    }
  } catch (_) {}

  // Calculate silence days and build risk list
  const now = Date.now()
  const allWithSilence = checkList.map(c => {
    const lastMsg = msgMap[c.wechat_id]
    const silenceDays = lastMsg?.sent_at
      ? Math.floor((now - new Date(lastMsg.sent_at).getTime()) / 86400000)
      : 999
    const salesInfo = SALES_LIST.find(s => s.wechatId === c.sales_wechat_id)
    return {
      contactName: c.remark || c.nickname || c.wechat_id,
      contactTag: c.contact_tag,
      salesName: salesInfo?.name || '未知',
      silenceDays,
      lastMessage: lastMsg?.content || null,
      lastMessageSender: lastMsg?.sender_type || null,
      lastMessageAt: lastMsg?.sent_at || null,
    }
  }).filter(c => c.silenceDays >= 14)

  // Top 10 risk signals
  const riskSignals = allWithSilence
    .sort((a, b) => b.silenceDays - a.silenceDays)
    .slice(0, 10)

  // Silence WoW: newly silent >14d this week vs last week
  // This week: last msg 14-20 days ago (crossed 14d threshold within 7 days)
  // Last week: last msg 21-27 days ago
  const silenceThisWeek = allWithSilence.filter(c => c.silenceDays >= 14 && c.silenceDays < 21).length
  const silenceLastWeek = allWithSilence.filter(c => c.silenceDays >= 21 && c.silenceDays < 28).length

  return { riskSignals, silenceThisWeek, silenceLastWeek }
}
