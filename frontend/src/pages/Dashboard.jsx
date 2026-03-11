import { useState, useEffect, useMemo } from 'react'
import { SALES_LIST } from '../lib/theme'
import {
  TIME_PRESETS,
  computeDateRange,
  fetchCoverageStats,
  fetchFunnelByAcquisition,
  fetchFunnelByTransaction,
  fetchPerformanceStats,
  fetchSalesFollowUp,
  fetchRiskAndSilence,
} from '../lib/dashboardQueries'

/* ═══════════════════════════════════════
   T-025 Design Tokens
   背景 #111110, 主色 #E8C47C, 成功 #6BCB77, 危险 #E85D5D
   漏斗色系: #7C9CE8, #8BC7E8, #E8C47C, #E8A84C, #6BCB77
   字体 DM Sans, 单列 540px maxWidth
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
  text: '#FFFFFF',
  textBody: 'rgba(255,255,255,0.85)',
  textSub: 'rgba(255,255,255,0.6)',
  textDim: 'rgba(255,255,255,0.4)',
  textMuted: 'rgba(255,255,255,0.2)',
  gradientBtn: 'linear-gradient(135deg, #E8C47C, #E8A84C)',
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

function ProgressRing({ value, target, size = 120, label }) {
  const stroke = 8
  const r = (size - stroke) / 2
  const circ = 2 * Math.PI * r
  const pct = Math.min(value, 100)
  const offset = circ * (1 - pct / 100)
  const color = value >= target ? D.green : value >= target * 0.7 ? D.gold : D.red

  return (
    <div style={{ textAlign: 'center' }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={size / 2} cy={size / 2} r={r}
          fill="none" stroke={D.border} strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r}
          fill="none" stroke={color} strokeWidth={stroke}
          strokeDasharray={circ} strokeDashoffset={offset}
          strokeLinecap="round"
          style={{ transition: 'stroke-dashoffset 0.8s ease' }}
        />
      </svg>
      <div style={{
        marginTop: -size / 2 - 16, position: 'relative', zIndex: 1,
        height: size / 2 + 16,
        display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      }}>
        <div style={{ fontSize: 28, fontWeight: 800, color: D.text }}>{pct}%</div>
        <div style={{ fontSize: 11, color: D.textDim }}>目标 {target}%</div>
      </div>
      {label && <div style={{ fontSize: 13, color: D.textSub, marginTop: 4 }}>{label}</div>}
    </div>
  )
}

function SalesBar({ name, done, total, color }) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0
  return (
    <div style={{ marginBottom: 10 }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 4,
      }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: D.text }}>{name}</span>
        <span style={{ fontSize: 12, color: D.textDim }}>{done}/{total} ({pct}%)</span>
      </div>
      <div style={{ background: D.bg, borderRadius: 4, height: 8, overflow: 'hidden' }}>
        <div style={{
          width: `${pct}%`, height: '100%', borderRadius: 4,
          background: color || D.gradientBtn,
          transition: 'width 0.5s ease',
        }} />
      </div>
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
  return (
    <Card title="跟进覆盖率">
      <div style={{ display: 'flex', justifyContent: 'center', padding: '8px 0' }}>
        <ProgressRing value={data.coveragePct} target={70} label="7日覆盖率" />
      </div>
      <div style={{
        display: 'flex', justifyContent: 'center', gap: 24,
        marginTop: 12, paddingTop: 12,
        borderTop: `1px solid ${D.borderSub}`,
      }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 20, fontWeight: 800, color: D.green }}>{data.tasksDone}</div>
          <div style={{ fontSize: 11, color: D.textDim }}>今日已跟</div>
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 20, fontWeight: 800, color: D.orange }}>{data.tasksPending}</div>
          <div style={{ fontSize: 11, color: D.textDim }}>今日待跟</div>
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 20, fontWeight: 800, color: D.textBody }}>{data.totalActive}</div>
          <div style={{ fontSize: 11, color: D.textDim }}>活跃客户</div>
        </div>
      </div>
      {!data.rpcAvailable && (
        <div style={{
          fontSize: 11, color: D.textMuted, textAlign: 'center',
          marginTop: 8, fontStyle: 'italic',
        }}>
          近似数据 · 部署SQL函数后获取精确值
        </div>
      )}
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

function FunnelCard({ data, funnelMode, onModeChange }) {
  if (!data) return null
  const maxVal = Math.max(...FUNNEL_STEPS.map(s => data[s.key] || 0), 1)
  const firstVal = data[FUNNEL_STEPS[0].key] || 0
  const lastVal = data[FUNNEL_STEPS[FUNNEL_STEPS.length - 1].key] || 0
  const totalConvRate = firstVal > 0 ? Math.round((lastVal / firstVal) * 100) : 0

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
      <div style={{ display: 'flex', gap: 4, marginBottom: 14 }}>
        {[
          { key: 'acquisition', label: '按获客' },
          { key: 'transaction', label: '按成交' },
        ].map(m => (
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

      {/* Funnel bars */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {FUNNEL_STEPS.map((step, i) => {
          const val = data[step.key] || 0
          const widthPct = maxVal > 0 ? Math.max((val / maxVal) * 100, 4) : 4

          // Step-to-step conversion rate
          const prevVal = i > 0 ? (data[FUNNEL_STEPS[i - 1].key] || 0) : null
          const stepRate = prevVal && prevVal > 0
            ? Math.round((val / prevVal) * 100)
            : null

          // Total conversion rate (this step / first step)
          const totalRate = i > 0 && firstVal > 0
            ? Math.round((val / firstVal) * 100)
            : null

          return (
            <div key={step.key}>
              <div style={{
                display: 'flex', justifyContent: 'space-between',
                alignItems: 'center', marginBottom: 3,
              }}>
                <span style={{ fontSize: 12, color: D.textSub, fontWeight: 600 }}>
                  {step.label}
                </span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ fontSize: 12, color: D.textDim }}>{val}</span>
                  {stepRate !== null && (
                    <span style={{ fontSize: 11, color: D.textMuted }}>
                      ↓{stepRate}%
                    </span>
                  )}
                  {totalRate !== null && (
                    <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.2)' }}>
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

  return (
    <Card title="业绩">
      <div style={{
        display: 'flex', justifyContent: 'space-around', textAlign: 'center',
        marginBottom: 16,
      }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 800, color: D.gold }}>
            {formatAmount(data.totalAmount)}
          </div>
          <div style={{ fontSize: 11, color: D.textDim }}>总金额(元)</div>
        </div>
        <div>
          <div style={{ fontSize: 22, fontWeight: 800, color: D.text }}>
            {data.totalOrders}
          </div>
          <div style={{ fontSize: 11, color: D.textDim }}>订单数</div>
        </div>
        {data.depositToWonRate !== null && (
          <div>
            <div style={{ fontSize: 22, fontWeight: 800, color: D.green }}>
              {data.depositToWonRate}%
            </div>
            <div style={{ fontSize: 11, color: D.textDim }}>定金转全款</div>
          </div>
        )}
      </div>

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
            const barColors = [D.gold, D.funnel[0], D.orange, D.green, D.red, D.funnel[1]]
            return (
              <div key={i} style={{ marginBottom: 8 }}>
                <div style={{
                  display: 'flex', justifyContent: 'space-between',
                  marginBottom: 3,
                }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: D.text }}>
                    {s.name}
                  </span>
                  <span style={{ fontSize: 12, color: D.textDim }}>
                    {formatAmount(s.amount)} · {s.count}单
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

  const COLORS = [D.funnel[0], D.gold, D.green, D.orange, D.red, D.funnel[1]]

  return (
    <Card title="销售跟进（今日）">
      {data.length > 0 ? data.map((s, i) => (
        <SalesBar
          key={s.wechatId}
          name={s.name}
          done={s.done}
          total={s.total}
          color={COLORS[i % COLORS.length]}
        />
      )) : (
        <div style={{ color: D.textDim, fontSize: 13, textAlign: 'center', padding: 16 }}>
          今日暂无任务数据
        </div>
      )}
    </Card>
  )
}

/* ═══ 5. Risk Signals Card ═══ */

function RiskSignalCard({ riskSignals, silenceThisWeek, silenceLastWeek }) {
  if (!riskSignals) return null

  const formatDate = (iso) => {
    if (!iso) return ''
    const d = new Date(iso)
    return `${d.getMonth() + 1}/${d.getDate()}`
  }

  // Silence WoW comparison badge
  const delta = silenceThisWeek - silenceLastWeek
  const deltaColor = delta > 0 ? D.red : delta < 0 ? D.green : D.textDim

  const silenceBadge = (
    <div style={{ textAlign: 'right' }}>
      <div style={{ fontSize: 11, color: D.textDim }}>本周新增沉默</div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 4, justifyContent: 'flex-end' }}>
        <span style={{ fontSize: 18, fontWeight: 800, color: deltaColor }}>
          {silenceThisWeek}
        </span>
        <span style={{ fontSize: 11, color: D.textDim }}>
          vs {silenceLastWeek}
        </span>
        {delta !== 0 && (
          <span style={{ fontSize: 12, fontWeight: 600, color: deltaColor }}>
            {delta > 0 ? `+${delta}` : delta}
          </span>
        )}
      </div>
    </div>
  )

  return (
    <Card title="沉默预警 · Top10" extra={silenceBadge}>
      {riskSignals.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {riskSignals.map((item, i) => {
            // >60天 red, >30天 gold, 其他 dim
            const dayColor = item.silenceDays > 60
              ? D.red
              : item.silenceDays > 30
                ? D.gold
                : 'rgba(255,255,255,0.4)'

            return (
              <div key={i} style={{
                background: D.bg, borderRadius: D.radiusSm,
                padding: '12px 14px',
                border: `1px solid ${item.silenceDays > 60 ? D.red + '40' : D.borderSub}`,
              }}>
                {/* Header */}
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
                    }}>
                      {item.salesName}
                      {item.contactTag && item.contactTag !== '未分类' && (
                        <span style={{
                          marginLeft: 6, color: D.gold,
                          border: `1px solid ${D.gold}44`, borderRadius: 3,
                          padding: '0 4px', fontSize: 10,
                        }}>
                          {item.contactTag}
                        </span>
                      )}
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

                {/* Last message */}
                {item.lastMessage && (
                  <div style={{
                    fontSize: 12, color: D.textDim, lineHeight: 1.4,
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    paddingTop: 6, borderTop: `1px solid ${D.borderSub}`,
                  }}>
                    <span style={{ color: item.lastMessageSender === 'sales' ? D.textSub : D.orange }}>
                      {item.lastMessageSender === 'sales' ? '销售' : '客户'}
                    </span>
                    {' '}
                    {formatDate(item.lastMessageAt)}
                    {'：'}
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
   Dashboard — T-025
   数据源: daily_tasks + contacts + orders + chat_messages
   区块: 覆盖率 / 漏斗(双视角) / 业绩 / 销售跟进 / 沉默预警Top10
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

  // Fetch sections that DON'T depend on time filter (coverage, follow-up, risk)
  useEffect(() => {
    fetchFixedSections()
  }, [])

  // Fetch sections that DO depend on time filter or funnel mode
  useEffect(() => {
    if (dateRange.start) fetchTimeSections()
  }, [dateRange.start, dateRange.end, funnelMode])

  const fetchFixedSections = async () => {
    setLoading(true)
    try {
      const [coverageData, followUpData, riskResult] = await Promise.all([
        fetchCoverageStats(),
        fetchSalesFollowUp(),
        fetchRiskAndSilence(),
      ])
      setCoverage(coverageData)
      setSalesFollowUp(followUpData)
      setRiskData(riskResult)
    } catch (err) {
      console.error('Dashboard fixed sections failed:', err)
    }
    setLoading(false)
  }

  const fetchTimeSections = async () => {
    try {
      const fetchFunnel = funnelMode === 'acquisition'
        ? fetchFunnelByAcquisition
        : fetchFunnelByTransaction

      const [funnelData, perfData] = await Promise.all([
        fetchFunnel(dateRange),
        fetchPerformanceStats(dateRange),
      ])
      setFunnel(funnelData)
      setPerformance(perfData)
    } catch (err) {
      console.error('Dashboard time sections failed:', err)
    }
  }

  const handleCustomChange = (start, end) => {
    setCustomStart(start)
    setCustomEnd(end)
  }

  if (loading) return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      padding: 80, fontFamily: D.font,
    }}>
      <div style={{ color: D.textDim, fontSize: 14 }}>加载中...</div>
    </div>
  )

  return (
    <div style={{ maxWidth: 540, margin: '0 auto', fontFamily: D.font }}>
      {/* Time filter (affects funnel + performance) */}
      <div style={{ padding: '0 16px' }}>
        <TimeFilter
          value={timePreset}
          onChange={setTimePreset}
          customStart={customStart}
          customEnd={customEnd}
          onCustomChange={handleCustomChange}
        />
      </div>

      <div style={{ padding: '8px 16px 0' }}>
        <CoverageCard data={coverage} />
        <FunnelCard
          data={funnel}
          funnelMode={funnelMode}
          onModeChange={setFunnelMode}
        />
        <PerformanceCard data={performance} />
        <SalesFollowUpCard data={salesFollowUp} />
        <RiskSignalCard
          riskSignals={riskData?.riskSignals}
          silenceThisWeek={riskData?.silenceThisWeek || 0}
          silenceLastWeek={riskData?.silenceLastWeek || 0}
        />
      </div>
    </div>
  )
}
