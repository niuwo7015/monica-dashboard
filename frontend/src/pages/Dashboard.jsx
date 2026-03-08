import { useState, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { supabase } from '../lib/supabase'
import { T, SALES_LIST, MAIN_SALES } from '../lib/theme'

/* ═══ Progress Ring (SVG) ═══ */
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

/* ═══ Bar Chart ═══ */
function SalesBar({ name, done, total, color }) {
  const pct = total > 0 ? Math.round((done / total) * 100) : 0
  return (
    <div style={{ marginBottom: 12 }}>
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

/* ═══ Stat Card ═══ */
function StatCard({ title, children }) {
  return (
    <div style={{
      background: T.bgCard, borderRadius: T.radius,
      border: `1px solid ${T.border}`, padding: 20, marginBottom: 12,
    }}>
      <div style={{
        fontSize: 14, fontWeight: 800, color: T.text,
        fontFamily: T.fontSerif, marginBottom: 14,
      }}>
        {title}
      </div>
      {children}
    </div>
  )
}

/* ═══════════════════════════════════════
   Dashboard — S-009
   数据源: daily_tasks + contacts + chat_messages
   ═══════════════════════════════════════ */
export default function Dashboard() {
  const { userProfile } = useAuth()
  const [loading, setLoading] = useState(true)
  const [todayStats, setTodayStats] = useState({ total: 0, done: 0 })
  const [salesStats, setSalesStats] = useState([])
  const [silentStats, setSilentStats] = useState({ gt3: 0, gt7: 0, gt14: 0 })
  const [newCustomerTrend, setNewCustomerTrend] = useState([])

  useEffect(() => { fetchDashboard() }, [])

  const fetchDashboard = async () => {
    setLoading(true)
    try {
      const today = new Date().toISOString().split('T')[0]

      // 1. Today's tasks — all sales
      const { data: allTasks } = await supabase
        .from('daily_tasks')
        .select('id, sales_wechat_id, status, priority, task_type, trigger_rule')
        .eq('task_date', today)

      const tasks = allTasks || []
      const totalTasks = tasks.length
      const doneTasks = tasks.filter(t => t.status === 'done').length
      setTodayStats({ total: totalTasks, done: doneTasks })

      // 2. Per-sales stats
      const salesMap = {}
      MAIN_SALES.forEach(s => { salesMap[s.wechatId] = { name: s.name, total: 0, done: 0 } })
      tasks.forEach(t => {
        if (salesMap[t.sales_wechat_id]) {
          salesMap[t.sales_wechat_id].total++
          if (t.status === 'done') salesMap[t.sales_wechat_id].done++
        }
      })
      setSalesStats(Object.values(salesMap))

      // 3. Silent customer stats — query with task_type
      const { data: silentData } = await supabase
        .from('daily_tasks')
        .select('task_type, trigger_rule')
        .eq('task_date', today)
        .in('task_type', ['follow_up_silent', 'reactivate'])

      let gt3 = 0, gt7 = 0, gt14 = 0
      ;(silentData || []).forEach(t => {
        const m = t.trigger_rule?.match(/(\d+)天/)
        const days = m ? parseInt(m[1]) : 0
        if (days > 14) gt14++
        else if (days > 7) gt7++
        else if (days > 3) gt3++
      })
      setSilentStats({ gt3, gt7, gt14 })

      // 4. New customers trend (last 7 days from contacts.created_at)
      const sevenDaysAgo = new Date()
      sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7)
      const { data: newContacts } = await supabase
        .from('contacts')
        .select('created_at')
        .gte('created_at', sevenDaysAgo.toISOString())
        .eq('is_deleted', 0)
        .eq('friend_type', 1)

      // Group by date
      const dailyCounts = {}
      for (let i = 6; i >= 0; i--) {
        const d = new Date()
        d.setDate(d.getDate() - i)
        dailyCounts[d.toISOString().split('T')[0]] = 0
      }
      ;(newContacts || []).forEach(c => {
        const d = c.created_at?.split('T')[0]
        if (d && dailyCounts[d] !== undefined) dailyCounts[d]++
      })
      setNewCustomerTrend(Object.entries(dailyCounts).map(([date, count]) => ({
        date, count,
        label: `${new Date(date).getMonth() + 1}/${new Date(date).getDate()}`,
      })))

    } catch (err) {
      console.error('Dashboard fetch failed:', err)
    }
    setLoading(false)
  }

  const coveragePct = todayStats.total > 0
    ? Math.round((todayStats.done / todayStats.total) * 100)
    : 0

  const maxTrend = Math.max(...newCustomerTrend.map(d => d.count), 1)

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 80 }}>
      <div style={{ color: T.textDim, fontSize: 14 }}>加载中...</div>
    </div>
  )

  return (
    <div style={{ padding: '16px 16px 0' }}>
      {/* Coverage rate */}
      <StatCard title="跟进覆盖率">
        <div style={{ display: 'flex', justifyContent: 'center', padding: '8px 0' }}>
          <ProgressRing value={coveragePct} target={70} label="今日完成率" />
        </div>
        <div style={{
          textAlign: 'center', fontSize: 12, color: T.textDim, marginTop: 8,
        }}>
          {todayStats.done} 已完成 / {todayStats.total} 总任务
        </div>
      </StatCard>

      {/* Per-sales completion */}
      <StatCard title="各销售跟进完成率">
        {salesStats.map((s, i) => (
          <SalesBar
            key={i} name={s.name}
            done={s.done} total={s.total}
            color={[T.rose, T.gold, T.green][i % 3]}
          />
        ))}
        {salesStats.every(s => s.total === 0) && (
          <div style={{ color: T.textDim, fontSize: 13, textAlign: 'center', padding: 16 }}>
            今日暂无任务数据
          </div>
        )}
      </StatCard>

      {/* Silent customers */}
      <StatCard title="沉默客户分布">
        <div style={{ display: 'flex', justifyContent: 'space-around', textAlign: 'center' }}>
          <div>
            <div style={{ fontSize: 24, fontWeight: 800, color: T.gold }}>{silentStats.gt3}</div>
            <div style={{ fontSize: 11, color: T.textDim }}>3-7天</div>
          </div>
          <div>
            <div style={{ fontSize: 24, fontWeight: 800, color: T.orange }}>{silentStats.gt7}</div>
            <div style={{ fontSize: 11, color: T.textDim }}>7-14天</div>
          </div>
          <div>
            <div style={{ fontSize: 24, fontWeight: 800, color: T.red }}>{silentStats.gt14}</div>
            <div style={{ fontSize: 11, color: T.textDim }}>14天+</div>
          </div>
        </div>
      </StatCard>

      {/* New customer trend */}
      <StatCard title="每日新增客户（近7天）">
        <div style={{
          display: 'flex', alignItems: 'flex-end',
          justifyContent: 'space-between', height: 100, gap: 4,
        }}>
          {newCustomerTrend.map((d, i) => {
            const h = maxTrend > 0 ? (d.count / maxTrend) * 80 : 0
            return (
              <div key={i} style={{
                flex: 1, display: 'flex', flexDirection: 'column',
                alignItems: 'center', gap: 4,
              }}>
                <span style={{ fontSize: 11, color: T.textBody, fontWeight: 600 }}>
                  {d.count > 0 ? d.count : ''}
                </span>
                <div style={{
                  width: '100%', maxWidth: 28,
                  height: Math.max(h, 2), borderRadius: 4,
                  background: d.count > 0 ? T.gradientBtn : T.border,
                  transition: 'height 0.5s ease',
                }} />
                <span style={{ fontSize: 10, color: T.textDim }}>{d.label}</span>
              </div>
            )
          })}
        </div>
      </StatCard>
    </div>
  )
}
