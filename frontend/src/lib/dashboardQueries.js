/* ═══════════════════════════════════════
   T-027b: Dashboard Data Queries (cached)
   前端优先读取服务器预计算的JSON缓存，秒开
   fallback到Supabase RPC（仅自定义时间范围）
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
  { key: '90d', label: '90天' },
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
    case '90d':
      return { start: fmtDate(daysAgo(today, 89)), end: fmtDate(today) }
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

// ─── Cache layer ───

let _cache = null
let _cacheTime = 0
const CACHE_TTL = 120000 // 2 min local cache

async function getCache() {
  if (_cache && Date.now() - _cacheTime < CACHE_TTL) return _cache
  try {
    const resp = await fetch('/api/dashboard.json?t=' + Math.floor(Date.now() / 60000))
    if (resp.ok) {
      _cache = await resp.json()
      _cacheTime = Date.now()
      return _cache
    }
  } catch (_) {}
  return null
}

function getCachedPreset(cache, preset) {
  if (!cache || !cache.presets) return null
  return cache.presets[preset] || null
}

// ═══════════════════════════════════════
// 1. Coverage Stats
// ═══════════════════════════════════════

export async function fetchCoverageStats(dateRange, preset) {
  const cache = await getCache()
  const cached = getCachedPreset(cache, preset)
  if (cached) return cached.coverage

  // Fallback: direct Supabase query
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
// ═══════════════════════════════════════

export async function fetchFunnelByAcquisition(dateRange, preset) {
  const empty = { added: 0, conversation: 0, quote: 0, deposit: 0, won: 0 }

  const cache = await getCache()
  const cached = getCachedPreset(cache, preset)
  if (cached) return cached.funnelCohort

  const { start, end } = dateRange
  if (!start) return empty

  try {
    const { data, error } = await supabase.rpc('dashboard_funnel_cohort', {
      p_sales_ids: CORE_IDS,
      p_start: start,
      p_end: end,
    })
    if (!error && data) {
      return {
        added: Number(data.added) || 0,
        conversation: Number(data.conversation) || 0,
        quote: Number(data.quote) || 0,
        deposit: Number(data.deposit) || 0,
        won: Number(data.won) || 0,
      }
    }
  } catch (_) {}

  return empty
}

// ═══════════════════════════════════════
// 2b. Funnel — 按成交 (period-based)
// ═══════════════════════════════════════

export async function fetchFunnelByTransaction(dateRange, preset) {
  const empty = { added: 0, conversation: 0, quote: 0, deposit: 0, won: 0 }

  const cache = await getCache()
  const cached = getCachedPreset(cache, preset)
  if (cached) return cached.funnelPeriod

  const { start, end } = dateRange
  if (!start) return empty

  try {
    const { data, error } = await supabase.rpc('dashboard_funnel_period', {
      p_sales_ids: CORE_IDS,
      p_start: start,
      p_end: end,
    })
    if (!error && data) {
      return {
        added: Number(data.added) || 0,
        conversation: Number(data.conversation) || 0,
        quote: Number(data.quote) || 0,
        deposit: Number(data.deposit) || 0,
        won: Number(data.won) || 0,
      }
    }
  } catch (_) {}

  return empty
}

// ═══════════════════════════════════════
// 3. Performance Stats
// ═══════════════════════════════════════

export async function fetchPerformanceStats(dateRange, preset) {
  const cache = await getCache()
  const cached = getCachedPreset(cache, preset)
  if (cached) return cached.performance

  // Fallback: direct query
  const { start, end } = dateRange

  const allOrders = []
  let offset = 0
  const pageSize = 1000
  while (true) {
    let q = supabase
      .from('orders')
      .select('amount, wechat_id, order_date, deal_cycle_days, sales_wechat_id, order_stage')
      .in('order_stage', ['won', 'deposit'])
    if (start) q = q.gte('order_date', start)
    if (end) q = q.lte('order_date', end)
    q = q.range(offset, offset + pageSize - 1)
    const { data } = await q
    const batch = data || []
    allOrders.push(...batch)
    if (batch.length < pageSize) break
    offset += pageSize
  }

  // 成交 = won + deposit(amount>1000)，deposit<=1000是阶段1订金不算成交
  const list = allOrders.filter(o =>
    o.order_stage === 'won' || (o.order_stage === 'deposit' && (parseFloat(o.amount) || 0) > 1000)
  )
  const totalAmount = list.reduce((sum, o) => sum + (parseFloat(o.amount) || 0), 0)
  const totalOrders = list.length
  const avgUnitPrice = totalOrders > 0 ? Math.round(totalAmount / totalOrders) : 0

  const withCycle = list.filter(o => o.deal_cycle_days != null)
  const avgDealCycle = withCycle.length > 0
    ? Math.round(withCycle.reduce((s, o) => s + o.deal_cycle_days, 0) / withCycle.length)
    : null

  const salesAgg = {}
  list.forEach(o => {
    const sid = o.sales_wechat_id || 'unknown'
    const name = CORE_MAP[sid] || '未知'
    if (!salesAgg[sid]) salesAgg[sid] = { name, amount: 0, count: 0, cycles: [] }
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
// ═══════════════════════════════════════

export async function fetchSalesFollowUp(dateRange, preset) {
  const cache = await getCache()
  const cached = getCachedPreset(cache, preset)
  if (cached) return cached.followUp

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
// 5. Risk Signals — Top 10
// ═══════════════════════════════════════

export async function fetchRiskSignals() {
  const cache = await getCache()
  if (cache && cache.risk_signals && cache.risk_signals.length > 0) {
    return cache.risk_signals
  }

  // Fallback: RPC
  try {
    const { data, error } = await supabase.rpc('dashboard_risk_top10', {
      p_sales_ids: CORE_IDS,
    })
    if (!error && data && data.length > 0) {
      return data.map(r => ({
        contactName: r.remark || r.nickname || r.wechat_id,
        salesName: CORE_MAP[r.sales_wechat_id] || '未知',
        silenceDays: r.silence_days,
        lastMessage: r.last_content || null,
        lastMessageAt: r.last_sent_at || null,
        followUpStatus: r.task_status === 'done' ? '已跟进' : '待跟进',
      }))
    }
  } catch (_) {}

  return []
}
