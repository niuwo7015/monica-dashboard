import { useState, useEffect, useMemo } from 'react'
import { T, SALES_LIST } from '../lib/theme'
import {
  TIME_PRESETS,
  computeDateRange,
  fetchCoverageStats,
  fetchFunnelStats,
  fetchPerformanceStats,
  fetchSalesFollowUp,
  fetchRiskSignals,
} from '../lib/dashboardQueries'

/* ═══ Shared Components ═══ */

function Card({ title, children, extra }) {
  return (
    <div style={{
      background: T.bgCard, borderRadius: T.radius,
      border: `1px solid ${T.border}`, padding: 20, marginBottom: 12,
    }}>
      <div style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        marginBottom: 14,
      }}>
        <div style={{
          fontSize: 14, fontWeight: 800, color: T.text,
          fontFamily: T.fontSerif,
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
  const color = value >= target ? T.green : value >= target * 0.7 ? T.gold : T.red

  return (
    <div style={{ textAlign: 'center' }}>
      <svg width={size} height={size} style={{ transform: 'rotate(-90deg)' }}>
        <circle cx={size / 2} cy={size / 2} r={r}
          fill="none" stroke={T.border} strokeWidth={stroke} />
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
        <div style={{ fontSize: 28, fontWeight: 800, color: T.text }}>{pct}%</div>
        <div style={{ fontSize: 11, color: T.textDim }}>目标 {target}%</div>
      </div>
      {label && <div style={{ fontSize: 13, color: T.textSub, marginTop: 4 }}>{label}</div>}
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
        <span style={{ fontSize: 13, fontWeight: 600, color: T.text }}>{name}</span>
        <span style={{ fontSize: 12, color: T.textDim }}>{done}/{total} ({pct}%)</span>
      </div>
      <div style={{ background: T.bg, borderRadius: 4, height: 8, overflow: 'hidden' }}>
        <div style={{
          width: `${pct}%`, height: '100%', borderRadius: 4,
          background: color || T.gradientBtn,
          transition: 'width 0.5s ease',
        }} />
      </div>
    </div>
  )
}

/* ═══ Time Filter ═══ */

function TimeFilter({ value, onChange }) {
  return (
    <div style={{
      display: 'flex', gap: 6, flexWrap: 'wrap',
      padding: '12px 16px 4px', marginBottom: 4,
    }}>
      {TIME_PRESETS.map(p => {
        const active = value === p.key
        return (
          <button
            key={p.key}
            onClick={() => onChange(p.key)}
            style={{
              padding: '5px 12px', fontSize: 12, fontWeight: 600,
              borderRadius: T.radiusPill,
              border: `1px solid ${active ? T.gold : T.border}`,
              background: active ? T.gold + '18' : 'transparent',
              color: active ? T.gold : T.textDim,
              cursor: 'pointer', fontFamily: T.fontSans,
              transition: 'all 0.2s',
            }}
          >
            {p.label}
          </button>
        )
      })}
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
        borderTop: `1px solid ${T.borderSub}`,
      }}>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 20, fontWeight: 800, color: T.green }}>{data.tasksDone}</div>
          <div style={{ fontSize: 11, color: T.textDim }}>今日已跟</div>
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 20, fontWeight: 800, color: T.orange }}>{data.tasksPending}</div>
          <div style={{ fontSize: 11, color: T.textDim }}>今日待跟</div>
        </div>
        <div style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 20, fontWeight: 800, color: T.textBody }}>{data.totalActive}</div>
          <div style={{ fontSize: 11, color: T.textDim }}>活跃客户</div>
        </div>
      </div>
      {!data.rpcAvailable && (
        <div style={{
          fontSize: 11, color: T.textMuted, textAlign: 'center',
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
  { key: 'added', label: '加微信', color: T.gold },
  { key: 'conversation', label: '有对话', color: T.caramel },
  { key: 'quote', label: '已报价', color: T.rose },
  { key: 'deposit', label: '付定金', color: T.orange },
  { key: 'won', label: '成交', color: T.green },
]

function FunnelCard({ data }) {
  if (!data) return null
  const maxVal = Math.max(...FUNNEL_STEPS.map(s => data[s.key] || 0), 1)

  return (
    <Card title="客户漏斗">
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {FUNNEL_STEPS.map((step, i) => {
          const val = data[step.key] || 0
          const widthPct = maxVal > 0 ? Math.max((val / maxVal) * 100, 4) : 4
          const prevVal = i > 0 ? (data[FUNNEL_STEPS[i - 1].key] || 0) : null
          const convRate = prevVal && prevVal > 0
            ? Math.round((val / prevVal) * 100)
            : null

          return (
            <div key={step.key}>
              <div style={{
                display: 'flex', justifyContent: 'space-between',
                alignItems: 'center', marginBottom: 3,
              }}>
                <span style={{ fontSize: 12, color: T.textSub, fontWeight: 600 }}>
                  {step.label}
                </span>
                <span style={{ fontSize: 12, color: T.textDim }}>
                  {val}
                  {convRate !== null && (
                    <span style={{ fontSize: 11, color: T.textMuted, marginLeft: 4 }}>
                      ({convRate}%)
                    </span>
                  )}
                </span>
              </div>
              <div style={{
                background: T.bg, borderRadius: 4, height: 20, overflow: 'hidden',
                display: 'flex', alignItems: 'center',
              }}>
                <div style={{
                  width: `${widthPct}%`, height: '100%', borderRadius: 4,
                  background: step.color,
                  transition: 'width 0.5s ease',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  minWidth: 28,
                }}>
                  <span style={{ fontSize: 11, fontWeight: 700, color: T.bg }}>
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
      {/* Summary */}
      <div style={{
        display: 'flex', justifyContent: 'space-around', textAlign: 'center',
        marginBottom: 16,
      }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 800, color: T.gold }}>
            {formatAmount(data.totalAmount)}
          </div>
          <div style={{ fontSize: 11, color: T.textDim }}>总金额(元)</div>
        </div>
        <div>
          <div style={{ fontSize: 22, fontWeight: 800, color: T.text }}>
            {data.totalOrders}
          </div>
          <div style={{ fontSize: 11, color: T.textDim }}>订单数</div>
        </div>
        {data.depositToWonRate !== null && (
          <div>
            <div style={{ fontSize: 22, fontWeight: 800, color: T.green }}>
              {data.depositToWonRate}%
            </div>
            <div style={{ fontSize: 11, color: T.textDim }}>定金转全款</div>
          </div>
        )}
      </div>

      {/* Per-sales breakdown */}
      {data.salesBreakdown.length > 0 && (
        <div style={{
          borderTop: `1px solid ${T.borderSub}`, paddingTop: 12,
        }}>
          <div style={{
            fontSize: 12, fontWeight: 600, color: T.textDim, marginBottom: 10,
          }}>
            各销售业绩
          </div>
          {data.salesBreakdown.map((s, i) => {
            const maxAmt = data.salesBreakdown[0]?.amount || 1
            const pct = Math.round((s.amount / maxAmt) * 100)
            return (
              <div key={i} style={{ marginBottom: 8 }}>
                <div style={{
                  display: 'flex', justifyContent: 'space-between',
                  marginBottom: 3,
                }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: T.text }}>
                    {s.name}
                  </span>
                  <span style={{ fontSize: 12, color: T.textDim }}>
                    {formatAmount(s.amount)} · {s.count}单
                  </span>
                </div>
                <div style={{ background: T.bg, borderRadius: 4, height: 6, overflow: 'hidden' }}>
                  <div style={{
                    width: `${pct}%`, height: '100%', borderRadius: 4,
                    background: [T.gold, T.rose, T.caramel, T.green, T.orange, T.red][i % 6],
                    transition: 'width 0.5s ease',
                  }} />
                </div>
              </div>
            )
          })}
        </div>
      )}

      {data.totalOrders === 0 && (
        <div style={{ color: T.textDim, fontSize: 13, textAlign: 'center', padding: 12 }}>
          该时间段暂无订单数据
        </div>
      )}
    </Card>
  )
}

/* ═══ 4. Sales Follow-up Card ═══ */

function SalesFollowUpCard({ data }) {
  if (!data) return null

  const COLORS = [T.rose, T.gold, T.green, T.caramel, T.orange, T.red]

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
        <div style={{ color: T.textDim, fontSize: 13, textAlign: 'center', padding: 16 }}>
          今日暂无任务数据
        </div>
      )}
    </Card>
  )
}

/* ═══ 5. Risk Signals Card ═══ */

function RiskSignalCard({ data }) {
  if (!data) return null

  const formatDate = (iso) => {
    if (!iso) return ''
    const d = new Date(iso)
    return `${d.getMonth() + 1}/${d.getDate()}`
  }

  return (
    <Card title="风险信号（沉默激活）">
      {data.length > 0 ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {data.map((item, i) => (
            <div key={i} style={{
              background: T.bg, borderRadius: T.radiusSm,
              padding: '12px 14px',
              border: `1px solid ${item.silenceDays > 30 ? T.red + '40' : T.borderSub}`,
            }}>
              {/* Header */}
              <div style={{
                display: 'flex', justifyContent: 'space-between',
                alignItems: 'flex-start', marginBottom: 6,
              }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    fontSize: 14, fontWeight: 700, color: T.text,
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {item.contactName}
                  </div>
                  <div style={{
                    fontSize: 11, color: T.textDim, marginTop: 2,
                  }}>
                    {item.salesName}
                    {item.contactTag && item.contactTag !== '未分类' && (
                      <span style={{
                        marginLeft: 6, color: T.gold,
                        border: `1px solid ${T.gold}44`, borderRadius: 3,
                        padding: '0 4px', fontSize: 10,
                      }}>
                        {item.contactTag}
                      </span>
                    )}
                  </div>
                </div>
                <div style={{
                  fontSize: 13, fontWeight: 800,
                  color: item.silenceDays > 30 ? T.red : item.silenceDays > 14 ? T.orange : T.gold,
                  whiteSpace: 'nowrap', marginLeft: 8,
                }}>
                  {item.silenceDays}天
                </div>
              </div>

              {/* Last message */}
              {item.lastMessage && (
                <div style={{
                  fontSize: 12, color: T.textDim, lineHeight: 1.4,
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  paddingTop: 6, borderTop: `1px solid ${T.borderSub}`,
                }}>
                  <span style={{ color: item.lastMessageSender === 'sales' ? T.textSub : T.caramel }}>
                    {item.lastMessageSender === 'sales' ? '销售' : '客户'}
                  </span>
                  {' '}
                  {formatDate(item.lastMessageAt)}
                  {'：'}
                  {item.lastMessage}
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div style={{ color: T.textDim, fontSize: 13, textAlign: 'center', padding: 16 }}>
          暂无沉默激活客户
        </div>
      )}
    </Card>
  )
}

/* ═══════════════════════════════════════
   Dashboard — T-022
   数据源: daily_tasks + contacts + orders + chat_messages
   五区块: 覆盖率 / 漏斗 / 业绩 / 销售跟进 / 风险
   ═══════════════════════════════════════ */
export default function Dashboard() {
  const [timePreset, setTimePreset] = useState('30d')
  const [loading, setLoading] = useState(true)

  // Data states
  const [coverage, setCoverage] = useState(null)
  const [funnel, setFunnel] = useState(null)
  const [performance, setPerformance] = useState(null)
  const [salesFollowUp, setSalesFollowUp] = useState(null)
  const [riskSignals, setRiskSignals] = useState(null)

  const dateRange = useMemo(() => computeDateRange(timePreset), [timePreset])

  // Fetch sections that DON'T depend on time filter (coverage, follow-up, risk)
  useEffect(() => {
    fetchFixedSections()
  }, [])

  // Fetch sections that DO depend on time filter (funnel, performance)
  useEffect(() => {
    fetchTimeSections()
  }, [dateRange.start, dateRange.end])

  const fetchFixedSections = async () => {
    setLoading(true)
    try {
      const [coverageData, followUpData, riskData] = await Promise.all([
        fetchCoverageStats(),
        fetchSalesFollowUp(),
        fetchRiskSignals(),
      ])
      setCoverage(coverageData)
      setSalesFollowUp(followUpData)
      setRiskSignals(riskData)
    } catch (err) {
      console.error('Dashboard fixed sections failed:', err)
    }
    setLoading(false)
  }

  const fetchTimeSections = async () => {
    try {
      const [funnelData, perfData] = await Promise.all([
        fetchFunnelStats(dateRange),
        fetchPerformanceStats(dateRange),
      ])
      setFunnel(funnelData)
      setPerformance(perfData)
    } catch (err) {
      console.error('Dashboard time sections failed:', err)
    }
  }

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 80 }}>
      <div style={{ color: T.textDim, fontSize: 14 }}>加载中...</div>
    </div>
  )

  return (
    <div>
      {/* Time filter (affects funnel + performance) */}
      <TimeFilter value={timePreset} onChange={setTimePreset} />

      <div style={{ padding: '8px 16px 0' }}>
        <CoverageCard data={coverage} />
        <FunnelCard data={funnel} />
        <PerformanceCard data={performance} />
        <SalesFollowUpCard data={salesFollowUp} />
        <RiskSignalCard data={riskSignals} />
      </div>
    </div>
  )
}
