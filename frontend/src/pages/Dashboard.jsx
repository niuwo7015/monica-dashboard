import { useState, useEffect, useMemo } from 'react'
import {
  TIME_PRESETS,
  computeDateRange,
  fetchCoverageStats,
  fetchFunnelByAcquisition,
  fetchFunnelByTransaction,
  fetchPerformanceStats,
  fetchSalesFollowUp,
  fetchRiskSignals,
} from '../lib/dashboardQueries'

/* ═══════════════════════════════════════
   T-025b Design Tokens
   背景 #111110, 主色 #E8C47C, DM Sans
   漏斗色系: #7C9CE8, #8BC7E8, #E8C47C, #E8A84C, #6BCB77
   ═══════════════════════════════════════ */
const D = {
  bg: '#111110',
  bgCard: 'rgba(255,255,255,0.03)',
  border: 'rgba(255,255,255,0.06)',
  borderSub: 'rgba(255,255,255,0.04)',
  gold: '#E8C47C',
  green: '#6BCB77',
  red: '#E85D5D',
  orange: '#E8A84C',
  yellow: '#E8C47C',
  text: '#FFFFFF',
  textBody: 'rgba(255,255,255,0.85)',
  textSub: 'rgba(255,255,255,0.6)',
  textDim: 'rgba(255,255,255,0.4)',
  textMuted: 'rgba(255,255,255,0.2)',
  font: '"DM Sans", "PingFang SC", -apple-system, sans-serif',
  radius: 16,
  radiusSm: 10,
  radiusPill: 20,
  funnel: ['#7C9CE8', '#8BC7E8', '#E8C47C', '#E8A84C', '#6BCB77'],
}

/* ═══ Shared Components ═══ */

function Card({ title, children, extra }) {
  return (
    <div style={{
      background: D.bgCard, borderRadius: D.radius,
      border: `1px solid ${D.border}`, padding: 20, marginBottom: 12,
    }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 14,
      }}>
        <div style={{
          fontSize: 14, fontWeight: 800, color: D.text,
          fontFamily: D.font,
        }}>
          {title}
        </div>
        {extra}
      </div>
      {children}
    </div>
  )
}

/* ═══ Time Filter ═══ */

function TimeFilter({ value, onChange, customStart, customEnd, onCustomChange }) {
  return (
    <div style={{ padding: '12px 0 4px', marginBottom: 4 }}>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
        {TIME_PRESETS.map(p => {
          const active = value === p.key
          return (
            <button
              key={p.key}
              onClick={() => onChange(p.key)}
              style={{
                padding: '5px 12px', fontSize: 12, fontWeight: 600,
                borderRadius: D.radiusPill,
                border: `1px solid ${active ? D.gold : D.border}`,
                background: active ? 'rgba(232,196,124,0.15)' : 'transparent',
                color: active ? D.gold : D.textDim,
                cursor: 'pointer', fontFamily: D.font,
                transition: 'all 0.2s',
              }}
            >
              {p.label}
            </button>
          )
        })}
      </div>
      {value === 'custom' && (
        <div style={{
          display: 'flex', gap: 8, marginTop: 8, alignItems: 'center',
        }}>
          <input
            type="date"
            value={customStart || ''}
            onChange={e => onCustomChange(e.target.value, customEnd)}
            style={{
              background: D.bg, border: `1px solid ${D.border}`,
              color: D.text, padding: '6px 10px', borderRadius: D.radiusSm,
              fontSize: 12, fontFamily: D.font, outline: 'none',
              colorScheme: 'dark',
            }}
          />
          <span style={{ color: D.textDim, fontSize: 12 }}>至</span>
          <input
            type="date"
            value={customEnd || ''}
            onChange={e => onCustomChange(customStart, e.target.value)}
            style={{
              background: D.bg, border: `1px solid ${D.border}`,
              color: D.text, padding: '6px 10px', borderRadius: D.radiusSm,
              fontSize: 12, fontFamily: D.font, outline: 'none',
              colorScheme: 'dark',
            }}
          />
        </div>
      )}
    </div>
  )
}

/* ═══ 1. Coverage Card ═══ */

function CoverageCard({ data }) {
  if (!data) return null
  const { pct, done, total, gap } = data
  const color = pct >= 70 ? D.green : pct >= 49 ? D.gold : D.red

  return (
    <Card title="跟进覆盖率">
      {/* Big number */}
      <div style={{ textAlign: 'center', marginBottom: 16 }}>
        <div style={{ fontSize: 48, fontWeight: 800, color, fontFamily: D.font }}>
          {pct}%
        </div>
      </div>

      {/* Progress bar with 70% target line */}
      <div style={{ position: 'relative', marginBottom: 8 }}>
        <div style={{
          background: D.bg, borderRadius: 6, height: 14, overflow: 'hidden',
        }}>
          <div style={{
            width: `${Math.min(pct, 100)}%`, height: '100%', borderRadius: 6,
            background: color,
            transition: 'width 0.5s ease',
          }} />
        </div>
        {/* 70% target marker */}
        <div style={{
          position: 'absolute', left: '70%', top: -4,
          width: 2, height: 22, background: D.text,
          opacity: 0.5,
        }} />
        <div style={{
          position: 'absolute', left: '70%', top: -16,
          transform: 'translateX(-50%)',
          fontSize: 10, color: D.textDim, fontWeight: 600,
        }}>
          70%
        </div>
      </div>

      {/* Stats row */}
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginTop: 12,
      }}>
        <div style={{ fontSize: 12, color: D.textSub }}>
          已跟进 <span style={{ fontWeight: 700, color: D.green }}>{done}</span>
          {' / '}
          应跟进 <span style={{ fontWeight: 700, color: D.text }}>{total}</span>
        </div>
        {gap > 0 && (
          <div style={{
            fontSize: 11, color: D.red, fontWeight: 600,
            background: 'rgba(232,93,93,0.1)',
            padding: '2px 8px', borderRadius: D.radiusPill,
          }}>
            缺口 {gap} 人
          </div>
        )}
      </div>
    </Card>
  )
}

/* ═══ 2. Funnel Card ═══ */

const FUNNEL_STEPS = [
  { key: 'added', label: '加微信' },
  { key: 'conversation', label: '有对话' },
  { key: 'quote', label: '已报价' },
  { key: 'deposit', label: '付定金' },
  { key: 'won', label: '成交' },
]

const FUNNEL_MODES = [
  { key: 'acquisition', label: '按获客', desc: '选定时间内加微的客户，追踪最终转化' },
  { key: 'transaction', label: '按成交', desc: '选定时间内各环节实际发生的动作数' },
]

function FunnelCard({ data, funnelMode, onModeChange }) {
  if (!data) return null
  const maxVal = Math.max(...FUNNEL_STEPS.map(s => data[s.key] || 0), 1)
  const firstVal = data[FUNNEL_STEPS[0].key] || 0
  const lastVal = data[FUNNEL_STEPS[FUNNEL_STEPS.length - 1].key] || 0
  const totalConvRate = firstVal > 0 ? Math.round((lastVal / firstVal) * 100) : 0
  const modeInfo = FUNNEL_MODES.find(m => m.key === funnelMode)

  return (
    <Card
      title="客户漏斗"
      extra={
        <div style={{ fontSize: 22, fontWeight: 800, color: D.gold, fontFamily: D.font }}>
          {totalConvRate}%
        </div>
      }
    >
      {/* Toggle: 按获客 / 按成交 */}
      <div style={{ marginBottom: 6 }}>
        <div style={{ display: 'flex', gap: 4, marginBottom: 6 }}>
          {FUNNEL_MODES.map(m => (
            <button
              key={m.key}
              onClick={() => onModeChange(m.key)}
              style={{
                padding: '4px 12px', fontSize: 11, fontWeight: 600,
                borderRadius: D.radiusPill,
                border: `1px solid ${funnelMode === m.key ? D.gold : D.border}`,
                background: funnelMode === m.key ? 'rgba(232,196,124,0.15)' : 'transparent',
                color: funnelMode === m.key ? D.gold : D.textDim,
                cursor: 'pointer', fontFamily: D.font,
                transition: 'all 0.2s',
              }}
            >
              {m.label}
            </button>
          ))}
        </div>
        {/* Explanation text */}
        <div style={{ fontSize: 11, color: D.textDim, lineHeight: 1.4 }}>
          {modeInfo?.desc}
        </div>
      </div>

      {/* Empty hint for cohort mode */}
      {firstVal === 0 && funnelMode === 'acquisition' && (
        <div style={{
          fontSize: 12, color: D.orange, textAlign: 'center',
          padding: '8px 0', lineHeight: 1.5,
        }}>
          该时间段无新增客户，试试选择「半年」或「全部」
        </div>
      )}

      {/* Funnel bars */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 10 }}>
        {FUNNEL_STEPS.map((step, i) => {
          const val = data[step.key] || 0
          const widthPct = maxVal > 0 ? Math.max((val / maxVal) * 100, 4) : 4

          const prevVal = i > 0 ? (data[FUNNEL_STEPS[i - 1].key] || 0) : null
          const stepRate = prevVal && prevVal > 0
            ? Math.round((val / prevVal) * 100) : null

          const totalRate = i > 0 && firstVal > 0
            ? Math.round((val / firstVal) * 100) : null

          return (
            <div key={step.key}>
              {/* Step-to-step arrow */}
              {stepRate !== null && (
                <div style={{
                  textAlign: 'center', fontSize: 10, color: D.textMuted,
                  margin: '-4px 0 2px',
                }}>
                  ↓ {stepRate}%
                </div>
              )}
              <div style={{
                display: 'flex', justifyContent: 'space-between',
                alignItems: 'center', marginBottom: 3,
              }}>
                <span style={{ fontSize: 12, color: D.textSub, fontWeight: 600 }}>
                  {step.label}
                </span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ fontSize: 12, color: D.textDim }}>{val}</span>
                  {totalRate !== null && (
                    <span style={{ fontSize: 11, color: D.textMuted }}>
                      {totalRate}%
                    </span>
                  )}
                </div>
              </div>
              <div style={{
                background: D.bg, borderRadius: 4, height: 20, overflow: 'hidden',
                display: 'flex', alignItems: 'center',
              }}>
                <div style={{
                  width: `${widthPct}%`, height: '100%', borderRadius: 4,
                  background: D.funnel[i],
                  transition: 'width 0.5s ease',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  minWidth: 28,
                }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: D.bg }}>
                    {val > 0 ? val : ''}
                  </span>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </Card>
  )
}

/* ═══ 3. Performance Card ═══ */

function PerformanceCard({ data }) {
  if (!data) return null

  const formatAmount = (n) => {
    if (n >= 10000) return (n / 10000).toFixed(1) + '万'
    return n.toLocaleString()
  }

  const cycleColor = (days) => {
    if (days == null) return D.textDim
    if (days <= 14) return D.green
    if (days <= 30) return D.yellow
    return D.red
  }

  return (
    <Card title="业绩">
      {/* Three KPI cards */}
      <div style={{
        display: 'flex', justifyContent: 'space-around', textAlign: 'center',
        marginBottom: 16,
      }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 800, color: D.gold }}>
            {formatAmount(data.totalAmount)}
          </div>
          <div style={{ fontSize: 11, color: D.textDim }}>成交总额(元)</div>
        </div>
        <div>
          <div style={{ fontSize: 22, fontWeight: 800, color: D.text }}>
            {data.totalOrders}
          </div>
          <div style={{ fontSize: 11, color: D.textDim }}>订单数</div>
        </div>
        <div>
          <div style={{
            fontSize: 22, fontWeight: 800,
            color: cycleColor(data.avgDealCycle),
          }}>
            {data.avgDealCycle != null ? `${data.avgDealCycle}天` : '-'}
          </div>
          <div style={{ fontSize: 11, color: D.textDim }}>平均成交周期</div>
        </div>
      </div>

      {/* Per-sales breakdown */}
      {data.salesBreakdown.length > 0 && (
        <div style={{
          borderTop: `1px solid ${D.borderSub}`, paddingTop: 12,
        }}>
          <div style={{
            fontSize: 12, fontWeight: 600, color: D.textDim, marginBottom: 10,
          }}>
            各销售业绩
          </div>
          {data.salesBreakdown.map((s, i) => {
            const maxAmt = data.salesBreakdown[0]?.amount || 1
            const pct = Math.round((s.amount / maxAmt) * 100)
            const barColors = [D.gold, D.funnel[0], D.green]
            return (
              <div key={i} style={{ marginBottom: 10 }}>
                <div style={{
                  display: 'flex', justifyContent: 'space-between',
                  marginBottom: 3,
                }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: D.text }}>
                    {s.name}
                  </span>
                  <span style={{ fontSize: 12, color: D.textDim }}>
                    {formatAmount(s.amount)} · {s.count}单
                    {s.avgCycle != null && (
                      <span style={{ color: cycleColor(s.avgCycle), marginLeft: 4 }}>
                        · {s.avgCycle}天
                      </span>
                    )}
                  </span>
                </div>
                <div style={{ background: D.bg, borderRadius: 4, height: 6, overflow: 'hidden' }}>
                  <div style={{
                    width: `${pct}%`, height: '100%', borderRadius: 4,
                    background: barColors[i % barColors.length],
                    transition: 'width 0.5s ease',
                  }} />
                </div>
              </div>
            )
          })}
        </div>
      )}

      {data.totalOrders === 0 && (
        <div style={{ color: D.textDim, fontSize: 13, textAlign: 'center', padding: 12 }}>
          该时间段暂无订单数据
        </div>
      )}
    </Card>
  )
}

/* ═══ 4. Sales Follow-up Card ═══ */

function SalesFollowUpCard({ data }) {
  if (!data) return null

  const rateColor = (pct) => {
    if (pct >= 50) return D.green
    if (pct >= 30) return D.yellow
    return D.red
  }

  return (
    <Card title="销售跟进">
      {data.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {data.map((s) => {
            const color = rateColor(s.pct)
            return (
              <div key={s.wechatId}>
                <div style={{
                  display: 'flex', justifyContent: 'space-between',
                  alignItems: 'center', marginBottom: 6,
                }}>
                  <span style={{ fontSize: 14, fontWeight: 700, color: D.text }}>
                    {s.name}
                  </span>
                  <span style={{ fontSize: 24, fontWeight: 800, color, fontFamily: D.font }}>
                    {s.pct}%
                  </span>
                </div>
                <div style={{
                  display: 'flex', justifyContent: 'space-between',
                  alignItems: 'center', marginBottom: 4,
                }}>
                  <span style={{ fontSize: 11, color: D.textDim }}>
                    {s.done}/{s.total} 已完成
                  </span>
                </div>
                <div style={{ background: D.bg, borderRadius: 4, height: 10, overflow: 'hidden' }}>
                  <div style={{
                    width: `${s.pct}%`, height: '100%', borderRadius: 4,
                    background: color,
                    transition: 'width 0.5s ease',
                  }} />
                </div>
              </div>
            )
          })}
        </div>
      ) : (
        <div style={{ color: D.textDim, fontSize: 13, textAlign: 'center', padding: 16 }}>
          该时间段暂无任务数据
        </div>
      )}
    </Card>
  )
}

/* ═══ 5. Risk Signals Card ═══ */

function RiskSignalCard({ data }) {
  if (!data) return null

  return (
    <Card title="风险信号 · Top10">
      {data.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {data.map((item, i) => {
            const isHighRisk = item.silenceDays > 30
            const dayColor = isHighRisk ? D.red : D.textSub

            return (
              <div key={i} style={{
                background: D.bg, borderRadius: D.radiusSm,
                padding: '12px 14px',
                border: `1px solid ${isHighRisk ? D.red + '40' : D.borderSub}`,
              }}>
                {/* Row 1: name + silence days */}
                <div style={{
                  display: 'flex', justifyContent: 'space-between',
                  alignItems: 'flex-start', marginBottom: 6,
                }}>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{
                      fontSize: 14, fontWeight: 700, color: D.text,
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>
                      {item.contactName}
                    </div>
                    <div style={{
                      fontSize: 11, color: D.textDim, marginTop: 2,
                      display: 'flex', alignItems: 'center', gap: 6,
                    }}>
                      <span>{item.salesName}</span>
                      <span style={{
                        color: item.followUpStatus === '已跟进' ? D.green : D.orange,
                        border: `1px solid ${item.followUpStatus === '已跟进' ? D.green + '44' : D.orange + '44'}`,
                        borderRadius: 3, padding: '0 4px', fontSize: 10,
                      }}>
                        {item.followUpStatus}
                      </span>
                    </div>
                  </div>
                  <div style={{
                    fontSize: 13, fontWeight: 800,
                    color: dayColor,
                    whiteSpace: 'nowrap', marginLeft: 8,
                  }}>
                    {item.silenceDays}天
                  </div>
                </div>

                {/* Row 2: last message */}
                {item.lastMessage && (
                  <div style={{
                    fontSize: 12, color: D.textDim, lineHeight: 1.4,
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    paddingTop: 6, borderTop: `1px solid ${D.borderSub}`,
                  }}>
                    {item.lastMessage}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      ) : (
        <div style={{ color: D.textDim, fontSize: 13, textAlign: 'center', padding: 16 }}>
          暂无沉默预警客户
        </div>
      )}
    </Card>
  )
}

/* ═══════════════════════════════════════
   Dashboard Main Component — T-025b
   ═══════════════════════════════════════ */

export default function Dashboard() {
  const [timePreset, setTimePreset] = useState('30d')
  const [customStart, setCustomStart] = useState('')
  const [customEnd, setCustomEnd] = useState('')
  const [funnelMode, setFunnelMode] = useState('acquisition')
  const [loading, setLoading] = useState(true)

  // Data states
  const [coverage, setCoverage] = useState(null)
  const [funnel, setFunnel] = useState(null)
  const [performance, setPerformance] = useState(null)
  const [salesFollowUp, setSalesFollowUp] = useState(null)
  const [riskData, setRiskData] = useState(null)

  const dateRange = useMemo(
    () => computeDateRange(timePreset, customStart, customEnd),
    [timePreset, customStart, customEnd]
  )

  // Today's date string
  const todayStr = useMemo(() => {
    const d = new Date()
    return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`
  }, [])

  // Inject DM Sans font
  useEffect(() => {
    const id = 'dm-sans-font'
    if (!document.getElementById(id)) {
      const link = document.createElement('link')
      link.id = id
      link.rel = 'stylesheet'
      link.href = 'https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700;800&display=swap'
      document.head.appendChild(link)
    }
  }, [])

  // Fetch risk signals (independent of time filter)
  useEffect(() => {
    fetchRiskSignals().then(setRiskData).catch(console.error)
  }, [])

  // Fetch all time-dependent sections
  useEffect(() => {
    if (!dateRange.start) return
    setLoading(true)

    const fetchFunnel = funnelMode === 'acquisition'
      ? fetchFunnelByAcquisition
      : fetchFunnelByTransaction

    Promise.all([
      fetchCoverageStats(dateRange),
      fetchFunnel(dateRange),
      fetchPerformanceStats(dateRange),
      fetchSalesFollowUp(dateRange),
    ]).then(([covData, funnelData, perfData, followData]) => {
      setCoverage(covData)
      setFunnel(funnelData)
      setPerformance(perfData)
      setSalesFollowUp(followData)
    }).catch(err => {
      console.error('Dashboard fetch failed:', err)
    }).finally(() => {
      setLoading(false)
    })
  }, [dateRange.start, dateRange.end, funnelMode])

  const handleCustomChange = (start, end) => {
    setCustomStart(start)
    setCustomEnd(end)
  }

  return (
    <div style={{ maxWidth: 540, margin: '0 auto', fontFamily: D.font }}>
      {/* Header */}
      <div style={{ padding: '16px 16px 0', textAlign: 'center' }}>
        <div style={{ fontSize: 18, fontWeight: 800, color: D.gold }}>
          管理仪表盘
        </div>
        <div style={{ fontSize: 12, color: D.textDim, marginTop: 4 }}>
          {todayStr}
        </div>
      </div>

      {/* Time filter */}
      <div style={{ padding: '0 16px' }}>
        <TimeFilter
          value={timePreset}
          onChange={setTimePreset}
          customStart={customStart}
          customEnd={customEnd}
          onCustomChange={handleCustomChange}
        />
      </div>

      {loading ? (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          padding: 80,
        }}>
          <div style={{ color: D.textDim, fontSize: 14 }}>加载中...</div>
        </div>
      ) : (
        <div style={{ padding: '8px 16px 0' }}>
          <CoverageCard data={coverage} />
          <FunnelCard
            data={funnel}
            funnelMode={funnelMode}
            onModeChange={setFunnelMode}
          />
          <PerformanceCard data={performance} />
          <SalesFollowUpCard data={salesFollowUp} />
          <RiskSignalCard data={riskData} />
        </div>
      )}
    </div>
  )
}
