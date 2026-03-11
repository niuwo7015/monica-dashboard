/* ═══════════════════════════════════════
   T-022: Dashboard Data Queries
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
  { key: 'all', label: '全部' },
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
    case 'all':
      return { start: null, end: null }
    case 'custom':
      return { start: customStart || null, end: customEnd || null }
    default:
      return { start: null, end: null }
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

// ─── 1. Coverage Stats ───

export async function fetchCoverageStats() {
  const today = fmtDate(new Date())

  // Daily tasks stats (always works)
  const { data: tasks } = await supabase
    .from('daily_tasks')
    .select('id, status')
    .eq('task_date', today)

  const allTasks = tasks || []
  const tasksDone = allTasks.filter(t => t.status === 'done').length
  const tasksPending = allTasks.filter(t => t.status === 'pending').length

  // Try RPC for precise coverage rate
  let totalActive = 0, followed7d = 0, rpcAvailable = false
  try {
    const { data, error } = await supabase.rpc('dashboard_coverage')
    if (!error && data) {
      totalActive = data.total_active || 0
      followed7d = data.followed_7d || 0
      rpcAvailable = true
    }
  } catch (_) { /* RPC not deployed yet */ }

  // Fallback: approximate from contacts + daily_tasks
  if (!rpcAvailable) {
    const { count: activeCount } = await supabase
      .from('contacts')
      .select('*', { count: 'exact', head: true })
      .eq('is_deleted', 0)
      .eq('friend_type', 1)
      .not('earliest_message_at', 'is', null)

    totalActive = activeCount || 0
    // Approximate followed_7d from daily_tasks completion
    followed7d = tasksDone
  }

  const coveragePct = totalActive > 0 ? Math.round((followed7d / totalActive) * 100) : 0

  return {
    coveragePct,
    totalActive,
    followed7d,
    tasksDone,
    tasksPending,
    rpcAvailable,
  }
}

// ─── 2. Funnel Stats ───

export async function fetchFunnelStats(dateRange) {
  const { start, end } = dateRange

  // 加微信 — contacts.add_time in range
  let addedQuery = supabase
    .from('contacts')
    .select('*', { count: 'exact', head: true })
    .eq('is_deleted', 0)
    .eq('friend_type', 1)
  if (start) addedQuery = addedQuery.gte('add_time', start)
  if (end) addedQuery = addedQuery.lte('add_time', end + 'T23:59:59')
  const { count: addedCount } = await addedQuery

  // 有对话 — try RPC, fallback to approximate
  let conversationCount = 0
  try {
    const { data, error } = await supabase.rpc('dashboard_funnel_conversations', {
      p_start: start || null,
      p_end: end || null,
    })
    if (!error && data !== null) {
      conversationCount = data
    }
  } catch (_) {
    // Fallback: contacts with earliest_message_at in range
    let fallbackQuery = supabase
      .from('contacts')
      .select('*', { count: 'exact', head: true })
      .eq('is_deleted', 0)
      .eq('friend_type', 1)
      .not('earliest_message_at', 'is', null)
    if (start) fallbackQuery = fallbackQuery.gte('add_time', start)
    if (end) fallbackQuery = fallbackQuery.lte('add_time', end + 'T23:59:59')
    const { count } = await fallbackQuery
    conversationCount = count || 0
  }

  // 已报价 — contacts.has_quote = true
  let quoteCount = 0
  try {
    let quoteQuery = supabase
      .from('contacts')
      .select('*', { count: 'exact', head: true })
      .eq('is_deleted', 0)
      .eq('friend_type', 1)
      .eq('has_quote', true)
    if (start) quoteQuery = quoteQuery.gte('add_time', start)
    if (end) quoteQuery = quoteQuery.lte('add_time', end + 'T23:59:59')
    const { count, error } = await quoteQuery
    if (!error) quoteCount = count || 0
  } catch (_) { /* has_quote column doesn't exist yet */ }

  // 付定金 + 成交 — from orders table
  let depositCount = 0, wonCount = 0
  try {
    // Try order_stage first (planned schema)
    let depositQuery = supabase
      .from('orders')
      .select('*', { count: 'exact', head: true })
      .eq('order_stage', 'deposit')
    if (start) depositQuery = depositQuery.gte('order_date', start)
    if (end) depositQuery = depositQuery.lte('order_date', end)
    const { count: dc, error: de } = await depositQuery

    let wonQuery = supabase
      .from('orders')
      .select('*', { count: 'exact', head: true })
      .eq('order_stage', 'won')
    if (start) wonQuery = wonQuery.gte('order_date', start)
    if (end) wonQuery = wonQuery.lte('order_date', end)
    const { count: wc, error: we } = await wonQuery

    if (!de) depositCount = dc || 0
    if (!we) wonCount = wc || 0

    // If order_stage doesn't exist, fallback: count all completed orders as "won"
    if (de && de.code === '42703') {
      let allOrdersQuery = supabase
        .from('orders')
        .select('*', { count: 'exact', head: true })
        .eq('order_status', 'completed')
      if (start) allOrdersQuery = allOrdersQuery.gte('order_date', start)
      if (end) allOrdersQuery = allOrdersQuery.lte('order_date', end)
      const { count } = await allOrdersQuery
      wonCount = count || 0
    }
  } catch (_) { /* orders table issue */ }

  return {
    added: addedCount || 0,
    conversation: conversationCount,
    quote: quoteCount,
    deposit: depositCount,
    won: wonCount,
  }
}

// ─── 3. Performance Stats ───

export async function fetchPerformanceStats(dateRange) {
  const { start, end } = dateRange

  let query = supabase
    .from('orders')
    .select('amount, sales_wechat_id, customer_wechat_id, order_date, order_status, order_stage')

  if (start) query = query.gte('order_date', start)
  if (end) query = query.lte('order_date', end)

  const { data: orders, error } = await query

  // If order_stage column doesn't exist, retry without it
  let orderList = orders || []
  if (error && error.code === '42703') {
    let retryQuery = supabase
      .from('orders')
      .select('amount, sales_wechat_id, customer_wechat_id, order_date, order_status')
    if (start) retryQuery = retryQuery.gte('order_date', start)
    if (end) retryQuery = retryQuery.lte('order_date', end)
    const { data } = await retryQuery
    orderList = data || []
  }

  // Total
  const totalAmount = orderList.reduce((sum, o) => sum + (parseFloat(o.amount) || 0), 0)
  const totalOrders = orderList.length

  // Per-sales breakdown
  const salesMap = {}
  SALES_LIST.forEach(s => {
    salesMap[s.wechatId] = { name: s.name, amount: 0, count: 0 }
  })
  orderList.forEach(o => {
    if (salesMap[o.sales_wechat_id]) {
      salesMap[o.sales_wechat_id].amount += parseFloat(o.amount) || 0
      salesMap[o.sales_wechat_id].count++
    }
  })
  const salesBreakdown = Object.values(salesMap)
    .filter(s => s.count > 0)
    .sort((a, b) => b.amount - a.amount)

  // Deposit → Won conversion: customers who have both stages
  let depositToWonRate = null
  const stageField = orderList[0]?.order_stage !== undefined ? 'order_stage' : null
  if (stageField) {
    const depositCustomers = new Set(
      orderList.filter(o => o[stageField] === 'deposit').map(o => o.customer_wechat_id)
    )
    const wonCustomers = new Set(
      orderList.filter(o => o[stageField] === 'won').map(o => o.customer_wechat_id)
    )
    const convertedCount = [...depositCustomers].filter(c => wonCustomers.has(c)).length
    depositToWonRate = depositCustomers.size > 0
      ? Math.round((convertedCount / depositCustomers.size) * 100)
      : null
  }

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

// ─── 5. Risk Signals ───

export async function fetchRiskSignals() {
  const today = fmtDate(new Date())

  // Get reactivate tasks (R3) sorted by priority (silence_days embedded in trigger_rule)
  const { data: riskTasks } = await supabase
    .from('daily_tasks')
    .select('contact_wechat_id, sales_wechat_id, trigger_rule, priority, status')
    .eq('task_date', today)
    .eq('task_type', 'reactivate')
    .order('priority', { ascending: false })
    .limit(10)

  if (!riskTasks || riskTasks.length === 0) return []

  // Get contact names
  const contactIds = [...new Set(riskTasks.map(t => t.contact_wechat_id))]
  const { data: contacts } = await supabase
    .from('contacts')
    .select('wechat_id, nickname, remark, contact_tag, sales_wechat_id')
    .in('wechat_id', contactIds)

  const contactMap = {}
  ;(contacts || []).forEach(c => {
    contactMap[c.wechat_id] = c
  })

  // Get last messages — try RPC first
  let msgMap = {}
  try {
    const { data: msgs, error } = await supabase.rpc('dashboard_last_messages', {
      p_wechat_ids: contactIds,
    })
    if (!error && msgs) {
      msgs.forEach(m => { msgMap[m.wechat_id] = m })
    }
  } catch (_) {
    // Fallback: query last message per contact in parallel
    const msgPromises = contactIds.map(async (id) => {
      const { data } = await supabase
        .from('chat_messages')
        .select('content, msg_content, sender_type, sent_at')
        .eq('wechat_id', id)
        .eq('is_system_msg', false)
        .order('sent_at', { ascending: false })
        .limit(1)
      if (data && data[0]) {
        msgMap[id] = {
          content: data[0].content || '[媒体消息]',
          sender_type: data[0].sender_type,
          sent_at: data[0].sent_at,
        }
      }
    })
    await Promise.all(msgPromises)
  }

  // Combine
  return riskTasks.map(task => {
    const contact = contactMap[task.contact_wechat_id] || {}
    const lastMsg = msgMap[task.contact_wechat_id]
    const silenceMatch = task.trigger_rule?.match(/(\d+)天/)
    const silenceDays = silenceMatch ? parseInt(silenceMatch[1]) : 0

    const salesInfo = SALES_LIST.find(s => s.wechatId === task.sales_wechat_id)

    return {
      contactName: contact.remark || contact.nickname || task.contact_wechat_id,
      contactTag: contact.contact_tag,
      salesName: salesInfo?.name || '未知',
      silenceDays,
      triggerRule: task.trigger_rule,
      status: task.status,
      lastMessage: lastMsg?.content || null,
      lastMessageSender: lastMsg?.sender_type || null,
      lastMessageAt: lastMsg?.sent_at || null,
    }
  }).sort((a, b) => b.silenceDays - a.silenceDays)
}
