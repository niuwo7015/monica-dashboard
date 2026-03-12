/* ═══════════════════════════════════════
   T-025b: Dashboard Data Queries
   管理仪表盘 Supabase 查询层
   所有查询仅限3个核心销售
   ═══════════════════════════════════════ */

import { supabase } from './supabase'
import { MAIN_SALES } from './theme'

// ─── Constants ───

const CORE_IDS = MAIN_SALES.map(s => s.wechatId)
const CORE_MAP = Object.fromEntries(MAIN_SALES.map(s => [s.wechatId, s.name]))

export const TIME_PRESETS = [
  { key: 'today', label: '今天' },
  { key: '7d', label: '7天' },
  { key: '14d', label: '14天' },
  { key: '30d', label: '30天' },
  { key: 'month', label: '本月' },
  { key: 'lastMonth', label: '上月' },
  { key: 'custom', label: '自定义' },
]

// ─── Time Range Helpers ───

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

// ─── Chunk helper for .in() queries ───

async function queryChunked(ids, queryFn, chunkSize = 200) {
  const results = []
  for (let i = 0; i < ids.length; i += chunkSize) {
    const chunk = ids.slice(i, i + chunkSize)
    const data = await queryFn(chunk)
    results.push(...(data || []))
  }
  return results
}

// ─── Cached core contact IDs ───
let _coreContactCache = null
let _coreContactCacheTime = 0

async function getCoreContactIds() {
  // Cache for 5 minutes
  if (_coreContactCache && Date.now() - _coreContactCacheTime < 300000) {
    return _coreContactCache
  }
  const { data } = await supabase
    .from('contacts')
    .select('wechat_id')
    .in('sales_wechat_id', CORE_IDS)
    .eq('is_deleted', 0)
    .eq('friend_type', 1)
  _coreContactCache = (data || []).map(c => c.wechat_id)
  _coreContactCacheTime = Date.now()
  return _coreContactCache
}

// ═══════════════════════════════════════
// 1. Coverage Stats
// 覆盖率% = 已跟进 / 应跟进 × 100
// ═══════════════════════════════════════

export async function fetchCoverageStats(dateRange) {
  const { start, end } = dateRange
  if (!start) return null

  const { data: tasks } = await supabase
    .from('daily_tasks')
    .select('id, status')
    .in('sales_wechat_id', CORE_IDS)
    .gte('task_date', start)
    .lte('task_date', end)

  const all = tasks || []
  const total = all.length
  const done = all.filter(t => t.status === 'done').length
  const pct = total > 0 ? Math.round(done / total * 100) : 0

  return { pct, done, total, gap: total - done }
}

// ═══════════════════════════════════════
// 2a. Funnel — 按获客 (cohort-based)
// 基准池 = contacts WHERE add_time在选定时间内
// 追踪这批人最终走到哪一步（不限时间）
// ═══════════════════════════════════════

export async function fetchFunnelByAcquisition(dateRange) {
  const { start, end } = dateRange
  if (!start) return { added: 0, conversation: 0, quote: 0, deposit: 0, won: 0 }

  // Base pool: contacts added in range, 3 core sales, friend_type=1
  const { data: cohort } = await supabase
    .from('contacts')
    .select('wechat_id')
    .in('sales_wechat_id', CORE_IDS)
    .eq('is_deleted', 0)
    .eq('friend_type', 1)
    .gte('add_time', start)
    .lte('add_time', end + 'T23:59:59')

  const ids = (cohort || []).map(c => c.wechat_id)
  const added = ids.length
  if (!added) return { added: 0, conversation: 0, quote: 0, deposit: 0, won: 0 }

  // 有对话: cohort members with any customer message (ever)
  const convIds = new Set()
  await queryChunked(ids, async (chunk) => {
    const { data } = await supabase
      .from('chat_messages')
      .select('wechat_id')
      .in('wechat_id', chunk)
      .eq('sender_type', 'customer')
      .eq('is_system_msg', false)
      .limit(1000)
    ;(data || []).forEach(m => convIds.add(m.wechat_id))
    return []
  })

  // 已报价: cohort members where sales sent price-like messages (ever)
  const quoteIds = new Set()
  await queryChunked(ids, async (chunk) => {
    const { data } = await supabase
      .from('chat_messages')
      .select('wechat_id')
      .in('wechat_id', chunk)
      .eq('sender_type', 'sales')
      .or('content.ilike.%元%,content.ilike.%价格%,content.ilike.%报价%')
      .limit(1000)
    ;(data || []).forEach(m => quoteIds.add(m.wechat_id))
    return []
  })

  // 付定金: cohort with deposit orders (ever)
  const depData = await queryChunked(ids, async (chunk) => {
    const { data } = await supabase
      .from('orders')
      .select('wechat_id')
      .in('wechat_id', chunk)
      .eq('order_stage', 'deposit')
    return data
  })
  const depositCount = new Set(depData.map(o => o.wechat_id)).size

  // 成交: cohort with won orders (ever)
  const wonData = await queryChunked(ids, async (chunk) => {
    const { data } = await supabase
      .from('orders')
      .select('wechat_id')
      .in('wechat_id', chunk)
      .eq('order_stage', 'won')
    return data
  })
  const wonCount = new Set(wonData.map(o => o.wechat_id)).size

  return {
    added,
    conversation: convIds.size,
    quote: quoteIds.size,
    deposit: depositCount,
    won: wonCount,
  }
}

// ═══════════════════════════════════════
// 2b. Funnel — 按成交 (period-based)
// 每层只算选定时间内发生的动作
// ═══════════════════════════════════════

export async function fetchFunnelByTransaction(dateRange) {
  const { start, end } = dateRange
  if (!start) return { added: 0, conversation: 0, quote: 0, deposit: 0, won: 0 }

  // 加微信: contacts added in range
  const { count: addedCount } = await supabase
    .from('contacts')
    .select('*', { count: 'exact', head: true })
    .in('sales_wechat_id', CORE_IDS)
    .eq('is_deleted', 0)
    .eq('friend_type', 1)
    .gte('add_time', start)
    .lte('add_time', end + 'T23:59:59')

  // 有对话: distinct customers who sent messages in range
  // Use RPC if available, otherwise query in chunks
  let conversationCount = 0
  try {
    const { data, error } = await supabase.rpc('dashboard_funnel_conversations', {
      p_start: start, p_end: end,
    })
    if (!error && data !== null) {
      conversationCount = data
    } else {
      throw new Error('RPC unavailable')
    }
  } catch (_) {
    // Fallback: query chat_messages in chunks using core contact IDs
    const allIds = await getCoreContactIds()
    const convIds = new Set()
    await queryChunked(allIds, async (chunk) => {
      const { data } = await supabase
        .from('chat_messages')
        .select('wechat_id')
        .in('wechat_id', chunk)
        .eq('sender_type', 'customer')
        .eq('is_system_msg', false)
        .gte('sent_at', start)
        .lte('sent_at', end + 'T23:59:59')
        .limit(1000)
      ;(data || []).forEach(m => convIds.add(m.wechat_id))
      return []
    }, 100)
    conversationCount = convIds.size
  }

  // 已报价: sales sent price messages in range
  let quoteCount = 0
  try {
    const allIds = await getCoreContactIds()
    const quoteIds = new Set()
    await queryChunked(allIds, async (chunk) => {
      const { data } = await supabase
        .from('chat_messages')
        .select('wechat_id')
        .in('wechat_id', chunk)
        .eq('sender_type', 'sales')
        .or('content.ilike.%元%,content.ilike.%价格%,content.ilike.%报价%')
        .gte('sent_at', start)
        .lte('sent_at', end + 'T23:59:59')
        .limit(1000)
      ;(data || []).forEach(m => quoteIds.add(m.wechat_id))
      return []
    }, 100)
    quoteCount = quoteIds.size
  } catch (_) {}

  // 付定金: orders in range with deposit stage (filter by core contacts)
  let depositCount = 0
  try {
    const coreIds = await getCoreContactIds()
    const depData = await queryChunked(coreIds, async (chunk) => {
      const { data } = await supabase
        .from('orders')
        .select('wechat_id')
        .in('wechat_id', chunk)
        .gte('order_date', start)
        .lte('order_date', end)
        .eq('order_stage', 'deposit')
      return data
    })
    depositCount = new Set(depData.map(o => o.wechat_id)).size
  } catch (_) {}

  // 成交: orders in range with won stage (filter by core contacts)
  let wonCount = 0
  try {
    const coreIds = await getCoreContactIds()
    const wonData = await queryChunked(coreIds, async (chunk) => {
      const { data } = await supabase
        .from('orders')
        .select('wechat_id')
        .in('wechat_id', chunk)
        .gte('order_date', start)
        .lte('order_date', end)
        .eq('order_stage', 'won')
      return data
    })
    wonCount = new Set(wonData.map(o => o.wechat_id)).size
  } catch (_) {}

  return {
    added: addedCount || 0,
    conversation: conversationCount,
    quote: quoteCount,
    deposit: depositCount,
    won: wonCount,
  }
}

// ═══════════════════════════════════════
// 3. Performance Stats
// 成交总额 + 订单数 + 平均成交周期
// 按销售拆分
// ═══════════════════════════════════════

export async function fetchPerformanceStats(dateRange) {
  const { start, end } = dateRange

  // Orders table has no sales_wechat_id — filter via core contacts
  const coreIds = await getCoreContactIds()

  // Build a wechat_id → sales_wechat_id map from contacts
  const { data: contactsForMap } = await supabase
    .from('contacts')
    .select('wechat_id, sales_wechat_id')
    .in('sales_wechat_id', CORE_IDS)
    .eq('is_deleted', 0)
    .eq('friend_type', 1)
  const wxToSales = Object.fromEntries(
    (contactsForMap || []).map(c => [c.wechat_id, c.sales_wechat_id])
  )

  // Fetch won orders for core contacts in date range
  const allOrders = await queryChunked(coreIds, async (chunk) => {
    let q = supabase
      .from('orders')
      .select('amount, wechat_id, order_date, deal_cycle_days')
      .in('wechat_id', chunk)
      .eq('order_stage', 'won')
    if (start) q = q.gte('order_date', start)
    if (end) q = q.lte('order_date', end)
    const { data } = await q
    return data
  })

  const list = allOrders || []
  const totalAmount = list.reduce((sum, o) => sum + (parseFloat(o.amount) || 0), 0)
  const totalOrders = list.length
  const avgUnitPrice = totalOrders > 0 ? Math.round(totalAmount / totalOrders) : 0

  // Average deal cycle (days)
  const withCycle = list.filter(o => o.deal_cycle_days != null)
  const avgDealCycle = withCycle.length > 0
    ? Math.round(withCycle.reduce((s, o) => s + o.deal_cycle_days, 0) / withCycle.length)
    : null

  // Per-sales breakdown using contacts mapping
  const salesAgg = {}
  list.forEach(o => {
    const sid = wxToSales[o.wechat_id] || 'unknown'
    const name = CORE_MAP[sid] || '未知'
    if (!salesAgg[sid]) {
      salesAgg[sid] = { name, amount: 0, count: 0, cycles: [] }
    }
    salesAgg[sid].amount += parseFloat(o.amount) || 0
    salesAgg[sid].count++
    if (o.deal_cycle_days != null) salesAgg[sid].cycles.push(o.deal_cycle_days)
  })

  const salesBreakdown = Object.entries(salesAgg)
    .filter(([sid]) => sid !== 'unknown')
    .map(([sid, v]) => ({
      wechatId: sid,
      name: v.name,
      amount: v.amount,
      count: v.count,
      avgCycle: v.cycles.length > 0
        ? Math.round(v.cycles.reduce((a, b) => a + b, 0) / v.cycles.length)
        : null,
    }))
    .sort((a, b) => b.amount - a.amount)

  return { totalAmount, totalOrders, avgUnitPrice, avgDealCycle, salesBreakdown }
}

// ═══════════════════════════════════════
// 4. Sales Follow-up
// 完成率 = done / total × 100, per sales
// ═══════════════════════════════════════

export async function fetchSalesFollowUp(dateRange) {
  const { start, end } = dateRange
  if (!start) return []

  const { data: tasks } = await supabase
    .from('daily_tasks')
    .select('sales_wechat_id, status')
    .in('sales_wechat_id', CORE_IDS)
    .gte('task_date', start)
    .lte('task_date', end)

  const salesMap = {}
  MAIN_SALES.forEach(s => {
    salesMap[s.wechatId] = { name: s.name, wechatId: s.wechatId, done: 0, total: 0 }
  })

  ;(tasks || []).forEach(t => {
    if (salesMap[t.sales_wechat_id]) {
      salesMap[t.sales_wechat_id].total++
      if (t.status === 'done') salesMap[t.sales_wechat_id].done++
    }
  })

  return Object.values(salesMap).map(s => ({
    ...s,
    pct: s.total > 0 ? Math.round(s.done / s.total * 100) : 0,
  }))
}

// ═══════════════════════════════════════
// 5. Risk Signals — Top 10 沉默客户
// 排除已成交客户，显示跟进状态
// ═══════════════════════════════════════

export async function fetchRiskSignals() {
  // Get won customer wechat_ids
  const wonIds = new Set()
  try {
    const { data } = await supabase
      .from('orders')
      .select('wechat_id')
      .eq('order_stage', 'won')
    ;(data || []).forEach(o => wonIds.add(o.wechat_id))
  } catch (_) {}

  // Get all active contacts for 3 core sales
  const { data: contacts } = await supabase
    .from('contacts')
    .select('wechat_id, nickname, remark, contact_tag, sales_wechat_id')
    .in('sales_wechat_id', CORE_IDS)
    .eq('is_deleted', 0)
    .eq('friend_type', 1)

  // Exclude won and sales wechat IDs
  const salesIdSet = new Set(CORE_IDS)
  const eligible = (contacts || []).filter(c =>
    !wonIds.has(c.wechat_id) && !salesIdSet.has(c.wechat_id)
  )

  if (!eligible.length) return []

  const contactIds = eligible.map(c => c.wechat_id)
  const contactMap = Object.fromEntries(eligible.map(c => [c.wechat_id, c]))

  // Get last messages via RPC
  let msgMap = {}
  try {
    const { data, error } = await supabase.rpc('dashboard_last_messages', {
      p_wechat_ids: contactIds.slice(0, 500),
    })
    if (!error && data) {
      data.forEach(m => { msgMap[m.wechat_id] = m })
    }
  } catch (_) {}

  // Get latest daily_task status per contact
  const taskStatusMap = {}
  try {
    const { data: tasks } = await supabase
      .from('daily_tasks')
      .select('contact_wechat_id, status, task_date')
      .in('contact_wechat_id', contactIds.slice(0, 500))
      .order('task_date', { ascending: false })
    // Keep only the latest task per contact
    ;(tasks || []).forEach(t => {
      if (!taskStatusMap[t.contact_wechat_id]) {
        taskStatusMap[t.contact_wechat_id] = t.status
      }
    })
  } catch (_) {}

  // Build risk list
  const now = Date.now()
  const withSilence = eligible.map(c => {
    const lastMsg = msgMap[c.wechat_id]
    const silenceDays = lastMsg?.sent_at
      ? Math.floor((now - new Date(lastMsg.sent_at).getTime()) / 86400000)
      : 999
    const taskStatus = taskStatusMap[c.wechat_id]

    return {
      contactName: c.remark || c.nickname || c.wechat_id,
      salesName: CORE_MAP[c.sales_wechat_id] || '未知',
      silenceDays,
      lastMessage: lastMsg?.content || null,
      lastMessageAt: lastMsg?.sent_at || null,
      followUpStatus: taskStatus === 'done' ? '已跟进' : '待跟进',
    }
  }).filter(c => c.silenceDays >= 7)

  return withSilence
    .sort((a, b) => b.silenceDays - a.silenceDays)
    .slice(0, 10)
}
