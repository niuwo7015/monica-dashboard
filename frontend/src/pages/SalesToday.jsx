import { useState, useEffect, useMemo } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { supabase } from '../lib/supabase'
import { T, TASK_TYPE_INFO, PRIORITY_GROUPS, getPriorityGroup, parseSilentDays } from '../lib/theme'

/* ═══ Helpers ═══ */
const fmtDate = d => {
  if (!d) return '—'
  const dt = new Date(d)
  return `${dt.getMonth() + 1}/${dt.getDate()}`
}

const motivation = pct => {
  if (pct === 0) return '今天的任务已准备好，开始跟进吧 ☕'
  if (pct < 50) return '正在推进中，节奏很好'
  if (pct < 100) return '过半了，今天状态不错'
  return '今天全部搞定，辛苦了'
}

/* ═══ Task Card ═══ */
function TaskCard({ task, contact, onDone, onUndo }) {
  const isDone = task.status === 'done'
  const typeInfo = TASK_TYPE_INFO[task.task_type] || { label: task.task_type, color: T.textSub }
  const silentDays = parseSilentDays(task.trigger_rule)
  const contactName = contact?.remark || contact?.nickname || task.contact_wechat_id

  return (
    <div style={{
      background: T.bgCard, borderRadius: T.radius,
      border: `1px solid ${isDone ? T.borderSub : T.border}`,
      marginBottom: 10, padding: 16,
      opacity: isDone ? 0.45 : 1,
      transition: 'opacity 0.3s',
    }}>
      {/* Row 1: Name + chips */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <span style={{ fontSize: 16, fontWeight: 800, color: T.text, fontFamily: T.fontSans }}>
          {contactName}
        </span>
        <span style={{
          fontSize: 11, fontWeight: 600, color: typeInfo.color,
          border: `1px solid ${typeInfo.color}66`, borderRadius: 4,
          padding: '2px 6px', fontFamily: T.fontSans,
        }}>
          {typeInfo.label}
        </span>
        {silentDays != null && (
          <span style={{
            fontSize: 11, fontWeight: 600, color: T.textSub,
            border: `1px solid ${T.border}`, borderRadius: 4,
            padding: '2px 6px', fontFamily: T.fontSans,
          }}>
            {silentDays}天未联系
          </span>
        )}
      </div>

      {/* Row 2: Trigger rule */}
      {task.trigger_rule && (
        <div style={{ fontSize: 13, color: T.textBody, lineHeight: 1.6, marginBottom: 8 }}>
          {task.trigger_rule}
        </div>
      )}

      {/* Row 3: Suggested action */}
      <div style={{
        fontSize: 13.5, color: T.gold, lineHeight: 1.6, marginBottom: 10,
        display: 'flex', alignItems: 'flex-start', gap: 6,
      }}>
        <span style={{ fontWeight: 700 }}>→</span>
        <span>{typeInfo.action || '跟进客户'}</span>
      </div>

      {/* Row 4: Contact tag */}
      {contact?.contact_tag && contact.contact_tag !== '未分类' && (
        <div style={{
          fontSize: 11, color: T.textDim, marginBottom: 10,
          display: 'flex', alignItems: 'center', gap: 4,
        }}>
          标签: {contact.contact_tag}
        </div>
      )}

      {/* Divider + action */}
      <div style={{ borderTop: `1px solid ${T.borderSub}`, margin: '8px 0' }} />
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: 12, color: T.textDim }}>
          {fmtDate(task.task_date)}
        </span>
        {isDone ? (
          <button
            onClick={() => onUndo(task.id)}
            style={{
              background: 'transparent', border: `1px solid ${T.border}`, borderRadius: T.radiusSm,
              color: T.green, padding: '8px 16px', fontSize: 12, fontWeight: 700,
              fontFamily: T.fontSans, cursor: 'pointer',
            }}
          >
            ✓ 已完成 · 撤回
          </button>
        ) : (
          <button
            onClick={() => onDone(task.id)}
            style={{
              background: T.gradientBtn, border: 'none', borderRadius: T.radiusPill,
              color: '#fff', padding: '8px 18px', fontSize: 13, fontWeight: 700,
              fontFamily: T.fontSans, cursor: 'pointer',
            }}
          >
            已完成
          </button>
        )}
      </div>
    </div>
  )
}

/* ═══════════════════════════════════════
   Main SalesToday — Phase 1
   数据源: daily_tasks + contacts
   ═══════════════════════════════════════ */
export default function SalesToday() {
  const { userProfile } = useAuth()
  const [tasks, setTasks] = useState([])
  const [contacts, setContacts] = useState({})
  const [loading, setLoading] = useState(true)

  useEffect(() => { fetchData() }, [userProfile])

  const fetchData = async () => {
    if (!userProfile) return
    setLoading(true)
    try {
      const today = new Date().toISOString().split('T')[0]

      const { data: taskData } = await supabase
        .from('daily_tasks')
        .select('*')
        .eq('sales_wechat_id', userProfile.salesWechatId)
        .eq('task_date', today)
        .order('priority', { ascending: false })

      const allTasks = taskData || []
      setTasks(allTasks)

      // Fetch contact info for all unique contact_wechat_ids
      const contactIds = [...new Set(allTasks.map(t => t.contact_wechat_id).filter(Boolean))]
      if (contactIds.length > 0) {
        const { data: contactData } = await supabase
          .from('contacts')
          .select('wechat_id, nickname, remark, contact_tag')
          .eq('sales_wechat_id', userProfile.salesWechatId)
          .in('wechat_id', contactIds)

        const map = {}
        contactData?.forEach(c => { map[c.wechat_id] = c })
        setContacts(map)
      }
    } catch (err) {
      console.error('Fetch failed:', err)
    }
    setLoading(false)
  }

  const handleDone = async (taskId) => {
    try {
      await supabase.from('daily_tasks').update({
        status: 'done',
        executed_at: new Date().toISOString(),
      }).eq('id', taskId)

      setTasks(prev => prev.map(t => t.id === taskId ? { ...t, status: 'done' } : t))
    } catch (err) {
      console.error('Update failed:', err)
    }
  }

  const handleUndo = async (taskId) => {
    try {
      await supabase.from('daily_tasks').update({
        status: 'pending',
        executed_at: null,
      }).eq('id', taskId)

      setTasks(prev => prev.map(t => t.id === taskId ? { ...t, status: 'pending' } : t))
    } catch (err) {
      console.error('Undo failed:', err)
    }
  }

  /* Group by priority */
  const grouped = useMemo(() => {
    const groups = {}
    PRIORITY_GROUPS.forEach(g => { groups[g.key] = [] })

    tasks.forEach(task => {
      const pg = getPriorityGroup(task.priority)
      if (groups[pg.key]) groups[pg.key].push(task)
    })

    return groups
  }, [tasks])

  /* Stats */
  const pendingTasks = tasks.filter(t => t.status === 'pending')
  const doneTasks = tasks.filter(t => t.status === 'done')
  const urgentCount = tasks.filter(t => t.priority >= 10 && t.status === 'pending').length
  const pct = tasks.length > 0 ? Math.round((doneTasks.length / tasks.length) * 100) : 0

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 80 }}>
      <div style={{ color: T.textDim, fontSize: 14, fontFamily: T.fontSans }}>加载中...</div>
    </div>
  )

  return (
    <div style={{ padding: '16px 16px 0' }}>
      {/* Stats card */}
      <div style={{
        background: T.bgCard, borderRadius: T.radius,
        border: `1px solid ${T.border}`, padding: 20, marginBottom: 16,
      }}>
        <div style={{
          display: 'flex', justifyContent: 'space-around',
          textAlign: 'center', marginBottom: 16,
        }}>
          <div>
            <div style={{ fontSize: 28, fontWeight: 800, color: T.text }}>{pendingTasks.length}</div>
            <div style={{ fontSize: 12, color: T.textDim }}>待跟进</div>
          </div>
          <div>
            <div style={{ fontSize: 28, fontWeight: 800, color: T.green }}>{doneTasks.length}</div>
            <div style={{ fontSize: 12, color: T.textDim }}>已完成</div>
          </div>
          <div>
            <div style={{ fontSize: 28, fontWeight: 800, color: T.red }}>{urgentCount}</div>
            <div style={{ fontSize: 12, color: T.textDim }}>紧急</div>
          </div>
        </div>

        {/* Progress bar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
          <div style={{ background: T.bg, borderRadius: 6, height: 6, flex: 1, overflow: 'hidden' }}>
            <div style={{
              width: `${pct}%`, height: '100%', borderRadius: 6,
              background: T.gradientBtn, transition: 'width 0.5s ease',
            }} />
          </div>
          <span style={{
            fontSize: 14, fontWeight: 700, color: T.gold,
            fontFamily: T.fontSerif, minWidth: 40, textAlign: 'right',
          }}>
            {pct}%
          </span>
        </div>
        <div style={{
          textAlign: 'center', fontSize: 12, color: T.textDim,
          fontStyle: 'italic',
        }}>
          {motivation(pct)}
        </div>
      </div>

      {/* Task groups */}
      {PRIORITY_GROUPS.map(pg => {
        const items = grouped[pg.key] || []
        if (items.length === 0) return null
        const pending = items.filter(t => t.status === 'pending')
        const done = items.filter(t => t.status === 'done')

        return (
          <div key={pg.key} style={{ marginBottom: 24 }}>
            {/* Group header */}
            <div style={{
              display: 'flex', justifyContent: 'space-between',
              alignItems: 'center', marginBottom: 10,
            }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                <span style={{ fontSize: 18 }}>{pg.emoji}</span>
                <span style={{
                  fontSize: 15, fontWeight: 800, color: T.text,
                  fontFamily: T.fontSerif,
                }}>{pg.label}</span>
                <span style={{ fontSize: 12, color: T.textDim }}>{pg.desc}</span>
              </div>
              <span style={{
                fontSize: 12, fontWeight: 700,
                background: `${pg.color}22`, color: pg.color,
                padding: '2px 10px', borderRadius: T.radiusPill,
              }}>{pending.length}</span>
            </div>

            {pending.map(task => (
              <TaskCard
                key={task.id} task={task}
                contact={contacts[task.contact_wechat_id]}
                onDone={handleDone} onUndo={handleUndo}
              />
            ))}
            {done.map(task => (
              <TaskCard
                key={task.id} task={task}
                contact={contacts[task.contact_wechat_id]}
                onDone={handleDone} onUndo={handleUndo}
              />
            ))}
          </div>
        )
      })}

      {/* Empty state */}
      {tasks.length === 0 && (
        <div style={{ textAlign: 'center', padding: '60px 20px', color: T.textDim }}>
          <div style={{ fontSize: 40, marginBottom: 16 }}>☕</div>
          <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>今天没有待办任务</div>
          <div style={{ fontSize: 13 }}>规则引擎还没生成今日任务</div>
        </div>
      )}
    </div>
  )
}
