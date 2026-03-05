import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { supabase } from '../lib/supabase'

/* ═══════════════════════════════════════
   Design Tokens v5 — 黑金玫瑰
   ═══════════════════════════════════════ */
const T = {
  bg: '#141214', bgCard: '#1e1c1e', bgModal: '#1a181a',
  border: '#363036', borderSub: '#2e2a2e',
  gold: '#d4a882', rose: '#b85068', caramel: '#c49070',
  gradientBtn: 'linear-gradient(135deg, #c49070, #b85068)',
  red: '#c06068', green: '#6bcf8e', orange: '#e8a44c',
  text: '#f2ece8', textBody: '#c4b8b0', textSub: '#a09098',
  textDim: '#787078', textMuted: '#585058',
  fontSans: '"PingFang SC", -apple-system, sans-serif',
  fontSerif: '"Noto Serif SC", "PingFang SC", serif',
  radius: 16, radiusSm: 10, radiusPill: 20,
}

/* ═══ Global CSS ═══ */
const INJECTED_CSS = `
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@500;700;900&display=swap');
@keyframes shake {
  0%   { transform: translateX(0) }
  15%  { transform: translateX(-4px) rotate(-0.5deg) }
  30%  { transform: translateX(4px) rotate(0.5deg) }
  45%  { transform: translateX(-3px) }
  60%  { transform: translateX(3px) }
  75%  { transform: translateX(-1px) }
  100% { transform: translateX(0) }
}
@keyframes particleFly {
  0%   { opacity:1; transform: translate(0,0) scale(1) }
  100% { opacity:0; transform: translate(var(--tx), var(--ty)) scale(0) }
}
@keyframes slideUp {
  0%   { opacity:0; transform: translateY(100%) }
  100% { opacity:1; transform: translateY(0) }
}
@keyframes fadeIn {
  0%   { opacity:0 }
  100% { opacity:1 }
}
::-webkit-scrollbar { width: 4px }
::-webkit-scrollbar-track { background: ${T.bg} }
::-webkit-scrollbar-thumb { background: ${T.border}; border-radius: 4px }
`

function useInjectCSS() {
  useEffect(() => {
    const id = 'sales-today-v5'
    if (!document.getElementById(id)) {
      const s = document.createElement('style')
      s.id = id
      s.textContent = INJECTED_CSS
      document.head.appendChild(s)
    }
  }, [])
}

/* ═══ Helpers ═══ */
const copy = t => navigator.clipboard.writeText(t)

const daysSince = d => d ? Math.floor((new Date() - new Date(d)) / 864e5) : null

const fmtDate = d => {
  if (!d) return '—'
  const dt = new Date(d)
  return `${dt.getMonth() + 1}/${dt.getDate()}`
}

const safeText = (v) => {
  if (v == null) return ''
  if (typeof v === 'string') return v
  if (typeof v === 'number') return String(v)
  if (Array.isArray(v)) return v.map(safeText).join('、')
  if (typeof v === 'object') {
    if (v.type) return v.type
    if (v.stage) return v.stage
    if (v.description) return v.description
    if (v.text) return v.text
    if (v.name) return v.name
    if (v.plain_explanation) return v.plain_explanation
  }
  return ''
}

const motivation = pct => {
  if (pct === 0) return '今天的功课AI帮你准备好了，开聊吧 ☕'
  if (pct < 50) return '正在推进中，节奏很好 ✨'
  if (pct < 100) return '过半了，你今天状态不错 💪'
  return '今天全部搞定，辛苦了 🎉'
}

/* ═══ Urgency Grouping Logic ═══ */
const URGENCY_GROUPS = {
  fire: {
    emoji: '🔥',
    title: '马上聊',
    desc: '客户在等你回复',
    color: T.rose,
  },
  chance: {
    emoji: '💡',
    title: '今天找机会',
    desc: '有试探任务或推进动作',
    color: T.orange,
  },
  keep: {
    emoji: '🌱',
    title: '保持联系',
    desc: '沉默激活 / 降频维护',
    color: T.green,
  },
}

const FIRE_TYPES = new Set([
  'reply', 'reply_new_message', 'follow_quote', 'follow_up_quote',
  'follow_sample', 'follow_up_sample', 'urgent', 'hot', 'closing',
])
const CHANCE_TYPES = new Set([
  'probe_need', 'probe_objection', 'probe_silent', 'probe_advance',
  'probe_value', 'probe_decision_maker', 'advance', 'push', 'probe',
])

function getUrgencyGroup(customer, la) {
  const actionType = la?.action_type || la?.do_this_today?.action_type || ''
  const treeNode = la?.tree_node || ''
  const silentDays = customer.silent_days ?? daysSince(customer.last_contact)

  // 🔥 马上聊
  if (FIRE_TYPES.has(actionType)) return 'fire'
  if (silentDays != null && silentDays === 0) return 'fire'
  if (treeNode.includes('reply') || treeNode.includes('quote_pending') || treeNode.includes('sample_pending')) return 'fire'
  if (customer.stage === 'negotiating' || customer.stage === 'closing') return 'fire'

  // 💡 今天找机会
  if (CHANCE_TYPES.has(actionType)) return 'chance'
  if (la?.probe_sub_type) return 'chance'
  if (treeNode.includes('probe') || treeNode.includes('advance')) return 'chance'

  // 🌱 保持联系
  return 'keep'
}

/* ═══ Follow-up type mapping ═══ */
const FOLLOW_TYPES = [
  { key: 'progress', emoji: '✅', label: '有进展', sub: '约寄样/报价/付款', color: T.green },
  { key: 'chatting', emoji: '💬', label: '在聊', sub: '还在沟通中', color: T.gold },
  { key: 'no_reply', emoji: '😶', label: '没回复', sub: '', color: T.textSub },
  { key: 'rejected', emoji: '❌', label: '明确拒绝', sub: '选了别家', color: T.red },
]

const chipSt = {
  fontSize: 11, fontWeight: 600, color: T.textSub,
  border: '1px solid #4a4048', borderRadius: 4, background: 'transparent',
  padding: '2px 6px', fontFamily: T.fontSans, whiteSpace: 'nowrap',
}

/* ═══ Particle Overlay ═══ */
function ParticleOverlay({ x, y, onDone }) {
  const COLORS = ['#c49070', '#b85068', '#d4a882', '#6bcf8e', '#f2ece8']
  const particles = useMemo(() =>
    Array.from({ length: 12 }, (_, i) => {
      const angle = (Math.PI * 2 * i) / 12 + (Math.random() - 0.5) * 0.5
      const dist = 30 + Math.random() * 50
      return {
        tx: Math.cos(angle) * dist,
        ty: Math.sin(angle) * dist,
        size: 3 + Math.random() * 5,
        color: COLORS[i % COLORS.length],
      }
    })
  , [])

  useEffect(() => {
    const t = setTimeout(onDone, 700)
    return () => clearTimeout(t)
  }, [onDone])

  return (
    <div style={{ position: 'fixed', left: x, top: y, pointerEvents: 'none', zIndex: 9999 }}>
      {particles.map((p, i) => (
        <div key={i} style={{
          position: 'absolute', width: p.size, height: p.size, borderRadius: '50%',
          background: p.color,
          '--tx': `${p.tx}px`, '--ty': `${p.ty}px`,
          animation: 'particleFly 0.7s ease-out forwards',
        }} />
      ))}
    </div>
  )
}

/* ═══ Copy Button ═══ */
function CopyBtn({ text }) {
  const [ok, setOk] = useState(false)
  if (!text) return null
  return (
    <button
      onClick={e => { e.stopPropagation(); copy(safeText(text)); setOk(true); setTimeout(() => setOk(false), 1500) }}
      style={{
        background: ok ? T.green : 'transparent',
        color: ok ? '#fff' : T.gold,
        border: ok ? 'none' : `1px solid ${T.gold}`,
        borderRadius: 8,
        padding: '5px 12px', fontSize: 12, fontWeight: 700,
        fontFamily: T.fontSans, cursor: 'pointer', transition: 'all 0.2s',
        display: 'inline-flex', alignItems: 'center', gap: 4,
      }}
    >
      📋 {ok ? '已复制' : '复制话术'}
    </button>
  )
}

/* ═══ Quick Record Panel (post-checkin modal) ═══ */
function QuickRecord({ customer, la, onSubmit, onClose }) {
  const [selected, setSelected] = useState(null)
  const [note, setNote] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async () => {
    if (!selected) return
    setSubmitting(true)
    await onSubmit(customer.id, selected, note, la)
    setSubmitting(false)
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 1000,
      background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)',
      display: 'flex', alignItems: 'flex-end', justifyContent: 'center',
      animation: 'fadeIn 0.2s ease',
    }} onClick={onClose}>
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: '100%', maxWidth: 640,
          background: T.bgModal, borderRadius: '20px 20px 0 0',
          border: `1px solid ${T.border}`, borderBottom: 'none',
          padding: '24px 20px 32px',
          animation: 'slideUp 0.3s ease',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <span style={{ fontSize: 16, fontWeight: 800, color: T.text, fontFamily: T.fontSerif }}>
            {customer.wechat_id || '客户'} · 今天聊得怎样？
          </span>
          <button onClick={onClose} style={{
            background: 'none', border: 'none', color: T.textDim, fontSize: 18, cursor: 'pointer',
          }}>✕</button>
        </div>

        {/* 4 outcome buttons */}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 16 }}>
          {FOLLOW_TYPES.map(ft => (
            <button key={ft.key}
              onClick={() => setSelected(ft.key)}
              style={{
                background: selected === ft.key ? `${ft.color}22` : T.bgCard,
                border: `1.5px solid ${selected === ft.key ? ft.color : T.border}`,
                borderRadius: T.radiusSm, padding: '14px 10px',
                cursor: 'pointer', textAlign: 'center', transition: 'all 0.2s',
              }}
            >
              <div style={{ fontSize: 22, marginBottom: 4 }}>{ft.emoji}</div>
              <div style={{ fontSize: 14, fontWeight: 700, color: selected === ft.key ? ft.color : T.text, fontFamily: T.fontSans }}>
                {ft.label}
              </div>
              {ft.sub && <div style={{ fontSize: 11, color: T.textDim, marginTop: 2 }}>{ft.sub}</div>}
            </button>
          ))}
        </div>

        {/* Optional note */}
        <textarea
          placeholder="补一句备注（选填）"
          value={note}
          onChange={e => setNote(e.target.value)}
          rows={2}
          style={{
            width: '100%', padding: '10px 12px', fontSize: 14,
            background: T.bgCard, border: `1px solid ${T.border}`, borderRadius: T.radiusSm,
            color: T.text, outline: 'none', boxSizing: 'border-box', fontFamily: T.fontSans,
            resize: 'none', marginBottom: 16,
          }}
        />

        {/* Submit */}
        <button
          onClick={handleSubmit}
          disabled={!selected || submitting}
          style={{
            width: '100%', padding: '14px 0', fontSize: 15, fontWeight: 800,
            background: selected ? T.gradientBtn : T.border,
            color: selected ? '#fff' : T.textMuted,
            border: 'none', borderRadius: T.radiusPill,
            cursor: selected ? 'pointer' : 'not-allowed',
            fontFamily: T.fontSans, transition: 'all 0.2s',
            opacity: submitting ? 0.6 : 1,
          }}
        >
          {submitting ? '提交中...' : '提交'}
        </button>
      </div>
    </div>
  )
}

/* ═══ Customer Card (List View) — v5 ═══ */
function Card({ customer, la, isDone, shaking, onCheckin, onUndo, onSelect }) {
  const silentDays = customer.silent_days ?? daysSince(customer.last_contact)
  const action = la?.action || la?.do_this_today?.action || ''
  const actionContent = la?.action_content || la?.do_this_today?.message_to_send || ''
  const bestTime = la?.best_time || la?.do_this_today?.best_time || ''
  const needHook = la?.need_hook
  const hookContent = la?.hook_content || ''
  const hookType = la?.hook_type || ''
  const probeSubType = la?.probe_sub_type || ''
  const treeNode = la?.tree_node || ''
  // Positive prompt — use verdict or a generated one
  const positivePrompt = la?.verdict || la?.positive_prompt || ''
  const name = customer.wechat_id || '未知客户'

  return (
    <div
      onClick={() => !isDone && onSelect(customer.id)}
      style={{
        background: T.bgCard, borderRadius: T.radius,
        border: `1px solid ${isDone ? T.borderSub : T.border}`,
        marginBottom: 10, padding: 16,
        opacity: isDone ? 0.45 : 1,
        cursor: isDone ? 'default' : 'pointer',
        transition: 'opacity 0.3s, border-color 0.3s',
        animation: shaking ? 'shake 0.4s' : 'none',
      }}
    >
      {/* Row 1: Name + chips */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
        <span style={{ fontSize: 17, fontWeight: 800, color: T.text, fontFamily: T.fontSans }}>{safeText(name)}</span>
        {silentDays != null && silentDays >= 0 && (
          <span style={chipSt}>{silentDays === 0 ? '今天有消息' : `${silentDays}天未联系`}</span>
        )}
        {probeSubType && <span style={{ ...chipSt, color: T.gold, borderColor: T.gold + '66' }}>{probeSubType.replace('probe_', '')}</span>}
      </div>

      {/* Row 2: Positive prompt */}
      {positivePrompt && (
        <div style={{ fontSize: 13, color: T.caramel, lineHeight: 1.6, marginBottom: 8, fontWeight: 500 }}>
          {safeText(positivePrompt)}
        </div>
      )}

      {/* Row 3: AI suggested action */}
      {action && (
        <div style={{ fontSize: 13.5, color: T.textBody, lineHeight: 1.7, marginBottom: 8 }}>
          <span style={{ color: T.gold, fontWeight: 700, marginRight: 6 }}>→</span>
          {safeText(action)}
        </div>
      )}

      {/* Row 4: Suggested script (copyable) */}
      {actionContent && (
        <div style={{
          background: '#242024', borderLeft: `3px solid ${T.gold}`, borderRadius: 6,
          padding: 12, fontSize: 13, color: T.text, lineHeight: 1.7, marginBottom: 8,
        }}>
          {safeText(actionContent)}
          <div style={{ marginTop: 8 }}>
            <CopyBtn text={actionContent} />
          </div>
        </div>
      )}

      {/* Row 5: Hook suggestion */}
      {needHook && hookContent && (
        <div style={{
          background: '#1e2420', borderLeft: `3px solid ${T.green}`, borderRadius: 6,
          padding: 10, fontSize: 12.5, color: T.green, lineHeight: 1.6, marginBottom: 8,
        }}>
          <span style={{ fontWeight: 700 }}>🎣 {hookType || '钩子'}：</span>{safeText(hookContent)}
        </div>
      )}

      {/* Divider */}
      <div style={{ borderTop: `1px solid ${T.borderSub}`, margin: '10px 0' }} />

      {/* Row 6: Best time + check-in button */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <span style={{ fontSize: 13, fontWeight: 700, color: T.gold, fontFamily: T.fontSerif }}>
          {bestTime ? `⏰ ${safeText(bestTime)}` : ''}
        </span>
        {isDone ? (
          <button
            onClick={e => { e.stopPropagation(); onUndo(customer.id) }}
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
            onClick={e => { e.stopPropagation(); onCheckin(customer.id, e) }}
            style={{
              background: T.gradientBtn, border: 'none', borderRadius: T.radiusPill,
              color: '#fff', padding: '8px 18px', fontSize: 13, fontWeight: 700,
              fontFamily: T.fontSans, cursor: 'pointer',
            }}
          >
            ✅ 今天聊过了
          </button>
        )}
      </div>
    </div>
  )
}

/* ═══ Section Container (Detail) ═══ */
function Sec({ title, children }) {
  return (
    <div style={{
      background: T.bgCard, borderRadius: T.radiusSm, padding: 16,
      border: `1px solid ${T.border}`, marginBottom: 12,
    }}>
      <div style={{ fontSize: 14, fontWeight: 700, color: T.text, marginBottom: 10 }}>{title}</div>
      {children}
    </div>
  )
}

/* ═══ Detail View ═══ */
function Detail({ customer, la, lb, lb_md, onBack }) {
  const [tab, setTab] = useState(0)
  const tabs = ['行动卡片', '决策简报', '全景报告']

  return (
    <div style={{ minHeight: '100vh', background: T.bg, color: T.text, fontFamily: T.fontSans, maxWidth: 640, margin: '0 auto' }}>
      <div style={{
        position: 'sticky', top: 0, zIndex: 100,
        background: 'rgba(20,18,20,0.92)', backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)',
        padding: '12px 16px 0', borderBottom: `1px solid ${T.border}`,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
          <button onClick={onBack} style={{
            background: 'none', border: 'none', color: T.gold, fontSize: 20, cursor: 'pointer', padding: 4,
          }}>←</button>
          <span style={{ fontSize: 17, fontWeight: 800, color: T.text }}>{safeText(customer.wechat_id) || '未知客户'}</span>
        </div>
        <div style={{ display: 'flex', gap: 24 }}>
          {tabs.map((t, i) => (
            <button key={t} onClick={() => setTab(i)} style={{
              background: 'none', border: 'none', fontFamily: T.fontSans,
              color: tab === i ? T.gold : T.textMuted,
              fontSize: 14, fontWeight: 600, padding: '8px 0', cursor: 'pointer',
              borderBottom: tab === i ? `2px solid ${T.gold}` : '2px solid transparent',
            }}>{t}</button>
          ))}
        </div>
      </div>
      <div style={{ padding: 16, paddingBottom: 60 }}>
        {tab === 0 && <TabAction la={la} />}
        {tab === 1 && <TabBrief la={la} lb={lb} />}
        {tab === 2 && <TabReport lb_md={lb_md} />}
      </div>
    </div>
  )
}

/* ═══ Tab 1: 行动卡片 ═══ */
function TabAction({ la }) {
  // 兼容Schema A (do_this_today嵌套) 和 Schema B (字段平铺)
  const action = la?.do_this_today || la || {}
  const actionText = la?.action || action.action || ''
  const actionContent = la?.action_content || action.message_to_send || action.action_content || ''
  const bestTime = la?.best_time || action.best_time || ''
  const needHook = la?.need_hook !== undefined ? la.need_hook : action.need_hook
  const hookContent = la?.hook_content || action.hook_content || ''
  const hookType = la?.hook_type || action.hook_type || ''

  return (
    <>
      {(la?.verdict || la?.positive_prompt) && (
        <Sec title="判断">
          <div style={{ fontSize: 13.5, color: T.textBody, lineHeight: 1.7 }}>{safeText(la.verdict || la.positive_prompt)}</div>
        </Sec>
      )}

      {la?.worth_pursuing && (
        <Sec title="值得跟吗">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
            <span style={{
              background: la.worth_pursuing.answer === '值得跟' ? T.green : T.red,
              color: '#fff', borderRadius: 4, padding: '2px 10px', fontSize: 13, fontWeight: 700
            }}>{safeText(la.worth_pursuing.answer)}</span>
            {la.worth_pursuing.win_probability && (
              <span style={{ fontSize: 12, color: T.gold }}>成单概率：{safeText(la.worth_pursuing.win_probability)}</span>
            )}
          </div>
          {la.worth_pursuing.reason && (
            <div style={{ fontSize: 13, color: T.textBody, lineHeight: 1.7, marginBottom: 8 }}>{safeText(la.worth_pursuing.reason)}</div>
          )}
          {la.worth_pursuing.similar_closed_pattern && (
            <div style={{ fontSize: 12, color: T.textSub, lineHeight: 1.6, borderLeft: `2px solid ${T.gold}`, paddingLeft: 10 }}>
              类似案例：{safeText(la.worth_pursuing.similar_closed_pattern)}
            </div>
          )}
        </Sec>
      )}

      {actionText && (
        <Sec title="下一步">
          <div style={{ fontSize: 13.5, color: T.textBody, lineHeight: 1.7 }}>{safeText(actionText)}</div>
          {bestTime && (
            <div style={{ marginTop: 8, fontSize: 13, fontWeight: 700, color: T.gold, fontFamily: T.fontSerif }}>
              ⏰ {safeText(bestTime)}
            </div>
          )}
        </Sec>
      )}

      {actionContent && (
        <Sec title="话术">
          <div style={{
            background: '#242024', borderLeft: `3px solid ${T.gold}`, borderRadius: 6,
            padding: 14, fontSize: 13.5, color: T.text, lineHeight: 1.7, marginBottom: 10,
          }}>
            {safeText(actionContent)}
          </div>
          <CopyBtn text={actionContent} />
        </Sec>
      )}

      {needHook && hookContent && (
        <Sec title={`🎣 钩子 · ${safeText(hookType)}`}>
          <div style={{
            background: '#1e2420', borderLeft: `3px solid ${T.green}`, borderRadius: 6,
            padding: 12, fontSize: 13.5, color: T.green, lineHeight: 1.7,
          }}>
            {safeText(hookContent)}
          </div>
          <div style={{ marginTop: 8 }}><CopyBtn text={hookContent} /></div>
        </Sec>
      )}

      {(action.if_customer_replies_yes || action.if_customer_replies_no || action.if_no_reply_3days) && (
        <Sec title="回复预案">
          {action.if_customer_replies_yes && (
            <div style={{
              background: '#1a2e1f', borderLeft: `3px solid ${T.green}`, borderRadius: 6,
              padding: 12, marginBottom: 8, fontSize: 13, color: T.green, lineHeight: 1.6,
            }}>
              <span style={{ fontWeight: 700 }}>积极回复：</span>{safeText(action.if_customer_replies_yes)}
            </div>
          )}
          {action.if_customer_replies_no && (
            <div style={{
              background: '#2e2a18', borderLeft: '3px solid #e8c468', borderRadius: 6,
              padding: 12, marginBottom: 8, fontSize: 13, color: '#e8c468', lineHeight: 1.6,
            }}>
              <span style={{ fontWeight: 700 }}>消极回复：</span>{safeText(action.if_customer_replies_no)}
            </div>
          )}
          {action.if_no_reply_3days && (
            <div style={{
              background: '#241a2e', borderLeft: '3px solid #b08cd8', borderRadius: 6,
              padding: 12, marginBottom: 8, fontSize: 13, color: '#b08cd8', lineHeight: 1.6,
            }}>
              <span style={{ fontWeight: 700 }}>3天没回：</span>{safeText(action.if_no_reply_3days)}
            </div>
          )}
        </Sec>
      )}

      {la?.one_trap_to_avoid && (
        <div style={{
          background: '#2e1a1a', borderRadius: T.radiusSm,
          border: '1px solid rgba(192,96,104,0.15)',
          padding: 14, fontSize: 13, color: T.red, lineHeight: 1.6, marginBottom: 12,
        }}>
          ⚠ {safeText(la.one_trap_to_avoid)}
        </div>
      )}
    </>
  )
}

/* ═══ Tab 2: 决策简报 ═══ */
function TabBrief({ lb, la }) {
  const snapshot = lb?.customer_snapshot || {}
  const stickingPoints = lb?.sticking_points || []
  const primarySticking = lb?.primary_sticking_point || ''
  const commGuide = lb?.communication_guide || {}
  const salesMirror = lb?.sales_mirror || {}
  const playbook = Array.isArray(lb?.playbook) ? lb.playbook : []

  return (
    <>
      <Sec title="客户画像">
        {snapshot.one_liner && (
          <div style={{ fontSize: 13.5, color: T.textBody, lineHeight: 1.7, marginBottom: 10 }}>{safeText(snapshot.one_liner)}</div>
        )}
        {snapshot.what_they_care_most && (
          <div style={{ fontSize: 12, color: T.textSub, marginBottom: 4 }}>最在意：{safeText(snapshot.what_they_care_most)}</div>
        )}
        {snapshot.how_they_decide && (
          <div style={{ fontSize: 12, color: T.textSub, marginBottom: 4 }}>决策方式：{safeText(snapshot.how_they_decide)}</div>
        )}
        {lb?.heat_trend && (
          <div style={{ fontSize: 12, color: T.textDim, marginTop: 6 }}>
            热度：{lb.heat_trend === 'warming' ? '升温中' : lb.heat_trend === 'cooling' ? '降温中' : lb.heat_trend === 'cold' ? '冷淡' : '稳定'}
          </div>
        )}
      </Sec>

      {(primarySticking || stickingPoints.length > 0) && (
        <Sec title="突破口">
          {primarySticking && (
            <div style={{ fontSize: 13.5, fontWeight: 600, color: T.gold, marginBottom: 8 }}>
              主要卡点：{safeText(primarySticking)}
            </div>
          )}
          {stickingPoints.map((sp, i) => (
            <div key={i} style={{ fontSize: 12, color: T.textBody, lineHeight: 1.6, marginBottom: 4 }}>
              · {typeof sp === 'string' ? sp : safeText(sp)}
            </div>
          ))}
        </Sec>
      )}

      {(commGuide.do || commGuide.dont || commGuide.tip) && (
        <Sec title="沟通要点">
          {commGuide.do && <div style={{ fontSize: 13, color: T.green, marginBottom: 6 }}>要做：{safeText(commGuide.do)}</div>}
          {commGuide.dont && <div style={{ fontSize: 13, color: T.red, marginBottom: 6 }}>别做：{safeText(commGuide.dont)}</div>}
          {commGuide.tip && <div style={{ fontSize: 13, color: T.gold, marginBottom: 6 }}>小技巧：{safeText(commGuide.tip)}</div>}
        </Sec>
      )}

      {(salesMirror.what_you_did_well || salesMirror.blind_spot || salesMirror.compared_to_closed) && (
        <Sec title="回顾与提升">
          {salesMirror.what_you_did_well && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: T.green, marginBottom: 4 }}>做得好</div>
              <div style={{ fontSize: 13, color: T.textBody, lineHeight: 1.6 }}>{safeText(salesMirror.what_you_did_well)}</div>
            </div>
          )}
          {salesMirror.blind_spot && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: T.gold, marginBottom: 4 }}>下次可以试试</div>
              <div style={{ fontSize: 13, color: T.textBody, lineHeight: 1.6 }}>{safeText(salesMirror.blind_spot)}</div>
            </div>
          )}
          {salesMirror.compared_to_closed && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: T.textSub, marginBottom: 4 }}>还有这些切入点没用上</div>
              <div style={{ fontSize: 13, color: T.textBody, lineHeight: 1.6 }}>{safeText(salesMirror.compared_to_closed)}</div>
            </div>
          )}
        </Sec>
      )}

      {playbook.length > 0 && (
        <Sec title="跟进计划">
          {playbook.map((step, i) => (
            <div key={i} style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: T.textSub, marginBottom: 4 }}>
                第{i + 1}步 {safeText(step.when || step.timing || '')}
              </div>
              <div style={{ fontSize: 13, color: T.textBody, lineHeight: 1.6 }}>
                {safeText(step.action || step.title || step.description || step)}
              </div>
              {(step.message_template || step.message) && (
                <div style={{
                  background: '#242024', borderLeft: `3px solid ${T.gold}`, borderRadius: 6,
                  padding: 10, marginTop: 6, fontSize: 13, color: T.text, lineHeight: 1.6,
                }}>
                  {safeText(step.message_template || step.message)}
                  <div style={{ marginTop: 8 }}><CopyBtn text={step.message_template || step.message} /></div>
                </div>
              )}
            </div>
          ))}
        </Sec>
      )}
    </>
  )
}

/* ═══ Tab 3: 全景报告 ═══ */
function TabReport({ lb_md }) {
  if (!lb_md) return (
    <div style={{ textAlign: 'center', color: T.textDim, padding: 40, fontSize: 13 }}>暂无全景报告</div>
  )
  return <MdLite text={lb_md} />
}

/* ═══ Markdown Lite ═══ */
function MdLite({ text }) {
  if (!text) return null
  const lines = text.split('\n')
  return (
    <div style={{ fontSize: 13, color: T.textBody, lineHeight: 2, fontFamily: T.fontSans }}>
      {lines.map((line, i) => {
        const t = line.trim()
        if (!t) return <div key={i} style={{ height: 8 }} />
        if (t.startsWith('### ')) return (
          <div key={i} style={{ fontSize: 14, fontWeight: 700, color: T.text, margin: '16px 0 8px' }}>
            {t.slice(4).replace(/\*\*/g, '')}
          </div>
        )
        if (t.startsWith('## ')) return (
          <div key={i} style={{ fontSize: 15, fontWeight: 800, color: T.text, margin: '20px 0 10px', fontFamily: T.fontSerif }}>
            {t.slice(3).replace(/\*\*/g, '')}
          </div>
        )
        if (t.startsWith('**') && t.endsWith('**')) return (
          <div key={i} style={{ fontWeight: 700, color: T.text, marginTop: 8, marginBottom: 4 }}>
            {t.replace(/\*\*/g, '')}
          </div>
        )
        if (t.includes('**')) {
          const parts = t.split(/(\*\*[^*]+\*\*)/)
          return (
            <div key={i} style={{ marginBottom: 2 }}>
              {parts.map((p, j) =>
                p.startsWith('**') && p.endsWith('**')
                  ? <span key={j} style={{ fontWeight: 700, color: T.text }}>{p.replace(/\*\*/g, '')}</span>
                  : <span key={j}>{p}</span>
              )}
            </div>
          )
        }
        if (t.startsWith('- ')) return <div key={i} style={{ paddingLeft: 12, marginBottom: 2 }}>· {t.slice(2)}</div>
        if (t.startsWith('| ') && !t.includes('---')) {
          const cells = t.split('|').filter(c => c.trim())
          if (cells.length === 2) return (
            <div key={i} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
              <span style={{ color: T.textDim }}>{cells[0].trim().replace(/\*\*/g, '')}</span>
              <span style={{ color: T.textBody }}>{cells[1].trim().replace(/\*\*/g, '')}</span>
            </div>
          )
        }
        return <div key={i} style={{ marginBottom: 2 }}>{t}</div>
      })}
    </div>
  )
}

/* ═══════════════════════════════════════
   Main SalesToday — v5
   ═══════════════════════════════════════ */
export default function SalesToday() {
  useInjectCSS()
  const { userProfile, signOut } = useAuth()
  const [customers, setCustomers] = useState([])
  const [diagnoses, setDiagnoses] = useState({})
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [selectedId, setSelectedId] = useState(null)
  const [shakingId, setShakingId] = useState(null)
  const [particleInfo, setParticleInfo] = useState(null)
  const [recordTarget, setRecordTarget] = useState(null) // customer being recorded
  const [doneTasks, setDoneTasks] = useState(() => {
    try {
      const saved = localStorage.getItem(`done_${new Date().toDateString()}`)
      return saved ? JSON.parse(saved) : []
    } catch { return [] }
  })

  useEffect(() => { fetchData() }, [userProfile])

  useEffect(() => {
    try { localStorage.setItem(`done_${new Date().toDateString()}`, JSON.stringify(doneTasks)) } catch {}
  }, [doneTasks])

  const fetchData = async () => {
    if (!userProfile) return
    setLoading(true)
    try {
      const [{ data: activeCusts }, { data: closedCusts }] = await Promise.all([
        supabase.from('customers').select('*')
          .eq('sales_id', userProfile.id)
          .neq('status', 'closed')
          .order('priority_score', { ascending: false }),
        supabase.from('customers').select('*')
          .eq('sales_id', userProfile.id)
          .eq('status', 'closed')
          .order('updated_at', { ascending: false }),
      ])

      const allCusts = [...(activeCusts || []), ...(closedCusts || [])]

      if (allCusts.length > 0) {
        const { data: diags } = await supabase
          .from('diagnoses').select('*')
          .in('customer_id', allCusts.map(c => c.id))
        const map = {}
        diags?.forEach(d => {
          try { d.layer_a = typeof d.layer_a === 'string' ? JSON.parse(d.layer_a) : d.layer_a } catch { d.layer_a = null }
          try { d.layer_b = typeof d.layer_b === 'string' ? JSON.parse(d.layer_b) : d.layer_b } catch { d.layer_b = null }
          map[d.customer_id] = d
        })
        setDiagnoses(map)
      }
      setCustomers(allCusts)
    } catch (err) { console.error('Fetch failed:', err) }
    setLoading(false)
  }

  /* Check-in: open quick record panel */
  const handleCheckin = (custId, e) => {
    const rect = e?.currentTarget?.getBoundingClientRect()
    if (rect) setParticleInfo({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2, key: Date.now() })
    setShakingId(custId)
    setTimeout(() => setShakingId(null), 400)

    const cust = customers.find(c => c.id === custId)
    if (cust) setRecordTarget(cust)
  }

  /* Submit follow-up record */
  const handleRecordSubmit = async (custId, followType, note, la) => {
    try {
      const aiSuggestion = la?.action || la?.do_this_today?.action || ''
      const aiActionType = la?.action_type || la?.do_this_today?.action_type || ''

      await supabase.from('follow_ups').insert({
        customer_id: custId,
        sales_id: userProfile.id,
        follow_type: followType,
        note: note || null,
        ai_suggestion: aiSuggestion || null,
        ai_action_type: aiActionType || null,
      })

      // Update last_contact on customer
      await supabase.from('customers').update({
        last_contact: new Date().toISOString(),
      }).eq('id', custId)

      // If rejected → update silence_count or mark
      if (followType === 'no_reply') {
        await supabase.from('customers').update({
          silence_count: (customers.find(c => c.id === custId)?.silence_count || 0) + 1,
        }).eq('id', custId)
      } else {
        await supabase.from('customers').update({ silence_count: 0 }).eq('id', custId)
      }
    } catch (err) {
      console.error('Record submit failed:', err)
    }

    setDoneTasks(prev => [...prev, custId])
    setRecordTarget(null)
  }

  const handleUndo = custId => setDoneTasks(prev => prev.filter(id => id !== custId))

  /* Urgency-based grouping — frozen=true excluded */
  const grouped = useMemo(() => {
    const g = { fire: [], chance: [], keep: [] }
    customers.forEach(c => {
      // Skip frozen customers
      if (c.frozen) return
      // Skip closed customers (aftersale handled separately if needed)
      if (c.status === 'closed') return

      const la = diagnoses[c.id]?.layer_a || {}
      const group = getUrgencyGroup(c, la)
      g[group].push(c)
    })
    // Sort each group by priority_score descending
    Object.keys(g).forEach(k =>
      g[k].sort((a, b) => (b.priority_score || 0) - (a.priority_score || 0))
    )
    return g
  }, [customers, diagnoses])

  /* Search filter */
  const filtered = useMemo(() => {
    if (!search.trim()) return grouped
    const q = search.toLowerCase()
    const f = arr => arr.filter(c =>
      c.wechat_id?.toLowerCase().includes(q) ||
      c.wechat_name?.toLowerCase().includes(q)
    )
    return { fire: f(grouped.fire), chance: f(grouped.chance), keep: f(grouped.keep) }
  }, [grouped, search])

  /* Stats */
  const activeCustomers = customers.filter(c => c.status !== 'closed' && !c.frozen)
  const total = activeCustomers.length
  const doneCount = doneTasks.length
  const pendingCount = Math.max(0, total - doneCount)
  const fireCount = grouped.fire.filter(c => !doneTasks.includes(c.id)).length
  const pct = total > 0 ? Math.round((doneCount / total) * 100) : 0

  /* ─── Detail view ─── */
  if (selectedId) {
    const customer = customers.find(c => c.id === selectedId)
    const diag = diagnoses[selectedId]
    if (customer) return (
      <Detail
        customer={customer}
        la={diag?.layer_a || {}}
        lb={diag?.layer_b || {}}
        lb_md={diag?.layer_b_md || ''}
        onBack={() => setSelectedId(null)}
      />
    )
  }

  /* ─── Loading ─── */
  if (loading) return (
    <div style={{ minHeight: '100vh', background: T.bg, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{ color: T.textDim, fontSize: 14, fontFamily: T.fontSans }}>加载中...</div>
    </div>
  )

  /* ─── List view ─── */
  return (
    <div style={{ minHeight: '100vh', background: T.bg, color: T.text, fontFamily: T.fontSans, maxWidth: 640, margin: '0 auto', paddingBottom: 40 }}>
      {/* Particle overlay */}
      {particleInfo && <ParticleOverlay x={particleInfo.x} y={particleInfo.y} key={particleInfo.key} onDone={() => setParticleInfo(null)} />}

      {/* Quick record modal */}
      {recordTarget && (
        <QuickRecord
          customer={recordTarget}
          la={diagnoses[recordTarget.id]?.layer_a || {}}
          onSubmit={handleRecordSubmit}
          onClose={() => setRecordTarget(null)}
        />
      )}

      <div style={{ padding: '16px 16px 0' }}>
        {/* ── Header Card ── */}
        <div style={{
          background: T.bgCard, borderRadius: T.radius, border: `1px solid ${T.border}`,
          padding: 20, marginBottom: 12,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
            <span style={{ fontSize: 16, fontWeight: 900, color: T.text, fontFamily: T.fontSerif }}>
              莫妮卡摩卡·{userProfile?.name || ''}
            </span>
            <button onClick={signOut} style={{
              background: 'none', border: `1px solid ${T.border}`, borderRadius: 8,
              color: T.textSub, padding: '4px 12px', fontSize: 12, cursor: 'pointer', fontFamily: T.fontSans,
            }}>退出</button>
          </div>
          <div style={{ fontSize: 12, color: T.textDim, marginBottom: 20 }}>
            AI的分析仅供参考，你比AI更懂你的客户 ✦
          </div>

          {/* Three stats */}
          <div style={{ display: 'flex', justifyContent: 'space-around', textAlign: 'center', marginBottom: 20 }}>
            <div>
              <div style={{ fontSize: 24, fontWeight: 800, color: T.text }}>{pendingCount}</div>
              <div style={{ fontSize: 12, color: T.textDim }}>待跟进</div>
            </div>
            <div>
              <div style={{ fontSize: 24, fontWeight: 800, color: T.green }}>{doneCount}</div>
              <div style={{ fontSize: 12, color: T.textDim }}>已完成</div>
            </div>
            <div>
              <div style={{ fontSize: 24, fontWeight: 800, color: T.rose }}>{fireCount}</div>
              <div style={{ fontSize: 12, color: T.textDim }}>🔥 紧急</div>
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
            <span style={{ fontSize: 13, fontWeight: 700, color: T.gold, fontFamily: T.fontSerif, minWidth: 36, textAlign: 'right' }}>
              {pct}%
            </span>
          </div>

          <div style={{ textAlign: 'center', fontSize: 12, fontWeight: 500, fontStyle: 'italic', color: T.textDim }}>
            {motivation(pct)}
          </div>
        </div>

        {/* ── Search ── */}
        <div style={{ position: 'relative', marginBottom: 16 }}>
          <input
            type="text" placeholder="搜索客户..." value={search}
            onChange={e => setSearch(e.target.value)}
            style={{
              width: '100%', padding: '10px 14px', fontSize: 14,
              background: T.bgCard, border: `1px solid ${T.border}`, borderRadius: T.radiusSm,
              color: T.text, outline: 'none', boxSizing: 'border-box', fontFamily: T.fontSans,
            }}
          />
          {search && (
            <button onClick={() => setSearch('')} style={{
              position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)',
              background: 'none', border: 'none', color: T.textDim, cursor: 'pointer', fontSize: 14,
            }}>✕</button>
          )}
        </div>
      </div>

      {/* ── Urgency Groups ── */}
      <div style={{ padding: '0 16px' }}>
        {['fire', 'chance', 'keep'].map(gk => {
          const items = filtered[gk] || []
          if (items.length === 0) return null
          const active = items.filter(c => !doneTasks.includes(c.id))
          const done = items.filter(c => doneTasks.includes(c.id))
          const meta = URGENCY_GROUPS[gk]
          return (
            <div key={gk} style={{ marginBottom: 24 }}>
              {/* Section header */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
                  <span style={{ fontSize: 18 }}>{meta.emoji}</span>
                  <span style={{ fontSize: 15, fontWeight: 800, color: T.text, fontFamily: T.fontSerif }}>{meta.title}</span>
                  <span style={{ fontSize: 12, fontWeight: 500, color: T.textDim }}>{meta.desc}</span>
                </div>
                <span style={{
                  fontSize: 12, fontWeight: 700,
                  background: gk === 'fire' ? T.gradientBtn : gk === 'chance' ? '#4a4028' : '#2a4038',
                  color: gk === 'fire' ? '#fff' : gk === 'chance' ? T.orange : T.green,
                  padding: '2px 10px', borderRadius: T.radiusPill,
                }}>{active.length}</span>
              </div>

              {active.map(c => {
                const diag = diagnoses[c.id]
                return (
                  <Card key={c.id} customer={c}
                    la={diag?.layer_a || {}}
                    isDone={false} shaking={shakingId === c.id}
                    onCheckin={handleCheckin} onUndo={handleUndo} onSelect={setSelectedId}
                  />
                )
              })}

              {done.map(c => {
                const diag = diagnoses[c.id]
                return (
                  <Card key={c.id} customer={c}
                    la={diag?.layer_a || {}}
                    isDone={true} shaking={false}
                    onCheckin={handleCheckin} onUndo={handleUndo} onSelect={setSelectedId}
                  />
                )
              })}
            </div>
          )
        })}

        {/* Empty state */}
        {grouped.fire.length === 0 && grouped.chance.length === 0 && grouped.keep.length === 0 && (
          <div style={{ textAlign: 'center', padding: '60px 20px', color: T.textDim }}>
            <div style={{ fontSize: 40, marginBottom: 16 }}>☕</div>
            <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>今天没有待办客户</div>
            <div style={{ fontSize: 13 }}>AI还没生成诊断，或者所有客户已冻结</div>
          </div>
        )}
      </div>
    </div>
  )
}
