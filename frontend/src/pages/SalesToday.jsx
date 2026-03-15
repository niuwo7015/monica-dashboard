import { useState, useEffect, useMemo } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { supabase } from '../lib/supabase'
import { T } from '../lib/theme'

/* ═══ 5-Action 定义 ═══ */
const ACTION_GROUPS = [
  { key: 'rush',    label: '立刻跟', emoji: '🔴', color: '#c06068', desc: '客户有明确推进信号' },
  { key: 'follow',  label: '持续跟', emoji: '🟠', color: '#e8a44c', desc: '有兴趣但时机不急' },
  { key: 'revive',  label: '值得捞', emoji: '🟡', color: '#d4c45c', desc: '沉默了但值得激活' },
  { key: 'nurture', label: '低优养着', emoji: '⚪', color: '#a09098', desc: '浅度接触，低频维护' },
  { key: 'drop',    label: '别浪费', emoji: '⛔', color: '#585058', desc: '明确拒绝或不匹配' },
]

/* ═══ 诊断卡片 ═══ */
function DiagCard({ diag, contact }) {
  const contactName = contact?.remark || contact?.nickname || diag.contact_wechat_id
  const group = ACTION_GROUPS.find(g => g.key === diag.action) || ACTION_GROUPS[3]

  return (
    <div style={{
      background: T.bgCard, borderRadius: T.radius,
      border: `1px solid ${T.border}`,
      marginBottom: 10, padding: 16,
    }}>
      {/* 行1: 客户名 + action标签 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <span style={{ fontSize: 16, fontWeight: 800, color: T.text, fontFamily: T.fontSans }}>
          {contactName}
        </span>
        <span style={{
          fontSize: 11, fontWeight: 600, color: group.color,
          border: `1px solid ${group.color}66`, borderRadius: 4,
          padding: '2px 6px', fontFamily: T.fontSans,
        }}>
          {group.emoji} {group.label}
        </span>
        {diag.msg_count > 0 && (
          <span style={{
            fontSize: 11, color: T.textDim,
            border: `1px solid ${T.border}`, borderRadius: 4,
            padding: '2px 6px',
          }}>
            {diag.msg_count}条消息
          </span>
        )}
        {diag.order_stage && (
          <span style={{
            fontSize: 11, color: T.green,
            border: `1px solid ${T.green}66`, borderRadius: 4,
            padding: '2px 6px',
          }}>
            {diag.order_stage === 'won' ? '已成交' : diag.order_stage === 'deposit' ? '已付定金' : diag.order_stage}
          </span>
        )}
      </div>

      {/* 行2: 判断依据 */}
      {diag.reason && (
        <div style={{ fontSize: 13, color: T.textBody, lineHeight: 1.6, marginBottom: 8 }}>
          {diag.reason}
        </div>
      )}

      {/* 行3: 建议动作 */}
      {diag.do_this && (
        <div style={{
          fontSize: 13.5, color: T.gold, lineHeight: 1.6, marginBottom: 8,
          display: 'flex', alignItems: 'flex-start', gap: 6,
        }}>
          <span style={{ fontWeight: 700 }}>→</span>
          <span>{diag.do_this}</span>
        </div>
      )}

      {/* 行4: 风险信号 */}
      {diag.risk && (
        <div style={{
          fontSize: 12, color: T.red, marginBottom: 8,
          display: 'flex', alignItems: 'center', gap: 4,
        }}>
          ⚠ {diag.risk}
        </div>
      )}

      {/* 底部分隔线 */}
      {(diag.order_stage || diag.msg_count > 0) && (
        <div style={{ borderTop: `1px solid ${T.borderSub}`, margin: '8px 0' }} />
      )}
    </div>
  )
}

/* ═══════════════════════════════════════
   SalesToday — Phase 2
   数据源: diagnoses（AI诊断5-action）
   ═══════════════════════════════════════ */
export default function SalesToday() {
  const { userProfile } = useAuth()
  const [diags, setDiags] = useState([])
  const [contacts, setContacts] = useState({})
  const [loading, setLoading] = useState(true)
  const [activeFilter, setActiveFilter] = useState('all')

  useEffect(() => { fetchData() }, [userProfile])

  const fetchData = async () => {
    if (!userProfile) return
    setLoading(true)
    try {
      // 取最新一天的诊断（不一定是今天）
      const { data: latestDate } = await supabase
        .from('diagnoses')
        .select('diagnosis_date')
        .eq('sales_wechat_id', userProfile.salesWechatId)
        .order('diagnosis_date', { ascending: false })
        .limit(1)

      const diagDate = latestDate?.[0]?.diagnosis_date
      if (!diagDate) { setLoading(false); return }

      const { data: diagData } = await supabase
        .from('diagnoses')
        .select('*')
        .eq('sales_wechat_id', userProfile.salesWechatId)
        .eq('diagnosis_date', diagDate)
        .order('action')

      const allDiags = diagData || []
      setDiags(allDiags)

      // 获取联系人信息
      const contactIds = [...new Set(allDiags.map(d => d.contact_wechat_id).filter(Boolean))]
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

  /* 按action分组 */
  const grouped = useMemo(() => {
    const groups = {}
    ACTION_GROUPS.forEach(g => { groups[g.key] = [] })

    diags.forEach(d => {
      if (groups[d.action]) groups[d.action].push(d)
    })

    // 排序：rush优先，rush内按消息数降序
    Object.values(groups).forEach(arr => {
      arr.sort((a, b) => (b.msg_count || 0) - (a.msg_count || 0))
    })

    return groups
  }, [diags])

  /* 过滤 */
  const filteredGroups = useMemo(() => {
    if (activeFilter === 'all') return grouped
    const result = {}
    ACTION_GROUPS.forEach(g => {
      result[g.key] = g.key === activeFilter ? grouped[g.key] : []
    })
    return result
  }, [grouped, activeFilter])

  /* 统计 */
  const actionCounts = useMemo(() => {
    const c = {}
    ACTION_GROUPS.forEach(g => { c[g.key] = (grouped[g.key] || []).length })
    return c
  }, [grouped])

  const diagDate = diags[0]?.diagnosis_date
  const fmtDiagDate = diagDate ? (() => {
    const d = new Date(diagDate + 'T00:00:00')
    return `${d.getMonth() + 1}月${d.getDate()}日`
  })() : ''

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 80 }}>
      <div style={{ color: T.textDim, fontSize: 14, fontFamily: T.fontSans }}>加载中...</div>
    </div>
  )

  return (
    <div style={{ padding: '16px 16px 0' }}>
      {/* 统计卡片 */}
      <div style={{
        background: T.bgCard, borderRadius: T.radius,
        border: `1px solid ${T.border}`, padding: 20, marginBottom: 16,
      }}>
        <div style={{
          fontSize: 13, color: T.textDim, textAlign: 'center', marginBottom: 12,
        }}>
          {fmtDiagDate} AI诊断 · {diags.length}位客户
        </div>
        <div style={{
          display: 'flex', justifyContent: 'space-around',
          textAlign: 'center', marginBottom: 8,
        }}>
          {ACTION_GROUPS.map(g => (
            <div key={g.key}
              onClick={() => setActiveFilter(activeFilter === g.key ? 'all' : g.key)}
              style={{ cursor: 'pointer', opacity: activeFilter !== 'all' && activeFilter !== g.key ? 0.3 : 1 }}
            >
              <div style={{ fontSize: 24, fontWeight: 800, color: g.color }}>
                {actionCounts[g.key]}
              </div>
              <div style={{ fontSize: 11, color: T.textDim }}>{g.emoji} {g.label}</div>
            </div>
          ))}
        </div>
        {activeFilter !== 'all' && (
          <div style={{ textAlign: 'center', marginTop: 8 }}>
            <button
              onClick={() => setActiveFilter('all')}
              style={{
                background: 'transparent', border: `1px solid ${T.border}`,
                borderRadius: T.radiusPill, color: T.textSub, padding: '4px 16px',
                fontSize: 12, cursor: 'pointer',
              }}
            >
              显示全部
            </button>
          </div>
        )}
      </div>

      {/* 按action分组展示 */}
      {ACTION_GROUPS.map(ag => {
        const items = filteredGroups[ag.key] || []
        if (items.length === 0) return null

        return (
          <div key={ag.key} style={{ marginBottom: 24 }}>
            {/* 分组标题 */}
            <div style={{
              display: 'flex', justifyContent: 'space-between',
              alignItems: 'center', marginBottom: 10,
            }}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                <span style={{ fontSize: 18 }}>{ag.emoji}</span>
                <span style={{
                  fontSize: 15, fontWeight: 800, color: T.text,
                  fontFamily: T.fontSerif,
                }}>{ag.label}</span>
                <span style={{ fontSize: 12, color: T.textDim }}>{ag.desc}</span>
              </div>
              <span style={{
                fontSize: 12, fontWeight: 700,
                background: `${ag.color}22`, color: ag.color,
                padding: '2px 10px', borderRadius: T.radiusPill,
              }}>{items.length}</span>
            </div>

            {items.map(d => (
              <DiagCard
                key={d.id} diag={d}
                contact={contacts[d.contact_wechat_id]}
              />
            ))}
          </div>
        )
      })}

      {/* 空状态 */}
      {diags.length === 0 && (
        <div style={{ textAlign: 'center', padding: '60px 20px', color: T.textDim }}>
          <div style={{ fontSize: 40, marginBottom: 16 }}>🤖</div>
          <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>暂无AI诊断数据</div>
          <div style={{ fontSize: 13 }}>等待诊断任务运行后自动更新</div>
        </div>
      )}
    </div>
  )
}
