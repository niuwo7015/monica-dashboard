import { useState, useEffect, useMemo } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { supabase } from '../lib/supabase'
import { T, MAIN_SALES, SALES_LIST } from '../lib/theme'

const EXCLUDE_TAGS = ['供应商', '同事', '私人']

/* ═══ Chat Preview ═══ */
function ChatBubble({ msg }) {
  const isSales = msg.sender_type === 'sales'
  return (
    <div style={{
      display: 'flex', justifyContent: isSales ? 'flex-end' : 'flex-start',
      marginBottom: 6,
    }}>
      <div style={{
        maxWidth: '80%', padding: '8px 12px', borderRadius: 10,
        fontSize: 13, lineHeight: 1.5,
        background: isSales ? '#2a2428' : T.bgCard,
        color: isSales ? T.textBody : T.text,
        border: `1px solid ${T.borderSub}`,
      }}>
        {msg.content || msg.msg_content || '[媒体消息]'}
      </div>
    </div>
  )
}

/* ═══ Customer Card ═══ */
function CustomerCard({ contact, expanded, onToggle }) {
  const [messages, setMessages] = useState([])
  const [loadingMsgs, setLoadingMsgs] = useState(false)
  const name = contact.remark || contact.nickname || contact.wechat_id

  useEffect(() => {
    if (expanded && messages.length === 0) {
      loadMessages()
    }
  }, [expanded])

  const loadMessages = async () => {
    setLoadingMsgs(true)
    try {
      const { data } = await supabase
        .from('chat_messages')
        .select('content, msg_content, sender_type, sent_at')
        .eq('wechat_id', contact.wechat_id)
        .order('sent_at', { ascending: false })
        .limit(5)

      setMessages((data || []).reverse())
    } catch (err) {
      console.error('Load messages failed:', err)
    }
    setLoadingMsgs(false)
  }

  return (
    <div style={{
      background: T.bgCard, borderRadius: T.radius,
      border: `1px solid ${T.border}`, marginBottom: 10,
      overflow: 'hidden',
    }}>
      <div
        onClick={onToggle}
        style={{
          padding: 16, cursor: 'pointer',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        }}
      >
        <div>
          <div style={{
            fontSize: 15, fontWeight: 700, color: T.text,
            fontFamily: T.fontSans, marginBottom: 4,
          }}>
            {name}
          </div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
            {contact.contact_tag && contact.contact_tag !== '未分类' && (
              <span style={{
                fontSize: 11, color: T.gold,
                border: `1px solid ${T.gold}66`, borderRadius: 4,
                padding: '1px 6px',
              }}>
                {contact.contact_tag}
              </span>
            )}
            {contact.region && (
              <span style={{
                fontSize: 11, color: T.textDim,
                border: `1px solid ${T.border}`, borderRadius: 4,
                padding: '1px 6px',
              }}>
                {contact.region}
              </span>
            )}
          </div>
        </div>
        <span style={{ color: T.textDim, fontSize: 16 }}>
          {expanded ? '▲' : '▼'}
        </span>
      </div>

      {/* Expanded: chat messages */}
      {expanded && (
        <div style={{
          borderTop: `1px solid ${T.borderSub}`,
          padding: 16, background: T.bg,
        }}>
          {loadingMsgs ? (
            <div style={{ color: T.textDim, fontSize: 13, textAlign: 'center', padding: 16 }}>
              加载聊天记录...
            </div>
          ) : messages.length === 0 ? (
            <div style={{ color: T.textDim, fontSize: 13, textAlign: 'center', padding: 16 }}>
              暂无聊天记录
            </div>
          ) : (
            <>
              <div style={{ fontSize: 12, color: T.textDim, marginBottom: 10 }}>最近 {messages.length} 条</div>
              {messages.map((msg, i) => (
                <ChatBubble key={i} msg={msg} />
              ))}
            </>
          )}
        </div>
      )}
    </div>
  )
}

/* ═══════════════════════════════════════
   CustomerList — S-008
   数据源: contacts + chat_messages
   ═══════════════════════════════════════ */
export default function CustomerList() {
  const { userProfile } = useAuth()
  const [allContacts, setAllContacts] = useState([])
  const [loading, setLoading] = useState(true)
  const [salesFilter, setSalesFilter] = useState('')
  const [tagFilter, setTagFilter] = useState('')
  const [expandedId, setExpandedId] = useState(null)
  const [search, setSearch] = useState('')

  useEffect(() => { fetchContacts() }, [])

  const fetchContacts = async () => {
    setLoading(true)
    try {
      // Fetch contacts for all 3 main sales (or current user's)
      let query = supabase
        .from('contacts')
        .select('*')
        .eq('is_deleted', 0)
        .eq('friend_type', 1)
        .order('updated_at', { ascending: false })

      const { data } = await query
      // Filter out excluded tags
      const filtered = (data || []).filter(c =>
        !EXCLUDE_TAGS.includes(c.contact_tag)
      )
      setAllContacts(filtered)
    } catch (err) {
      console.error('Fetch contacts failed:', err)
    }
    setLoading(false)
  }

  /* Available tags for filter */
  const availableTags = useMemo(() => {
    const tags = new Set()
    allContacts.forEach(c => {
      if (c.contact_tag && c.contact_tag !== '未分类') tags.add(c.contact_tag)
    })
    return [...tags].sort()
  }, [allContacts])

  /* Filter contacts */
  const filtered = useMemo(() => {
    let list = allContacts

    if (salesFilter) {
      list = list.filter(c => c.sales_wechat_id === salesFilter)
    }
    if (tagFilter) {
      list = list.filter(c => c.contact_tag === tagFilter)
    }
    if (search.trim()) {
      const q = search.toLowerCase()
      list = list.filter(c =>
        c.wechat_id?.toLowerCase().includes(q) ||
        c.nickname?.toLowerCase().includes(q) ||
        c.remark?.toLowerCase().includes(q)
      )
    }

    return list
  }, [allContacts, salesFilter, tagFilter, search])

  const selectStyle = {
    background: T.bgCard, border: `1px solid ${T.border}`,
    borderRadius: T.radiusSm, padding: '8px 12px',
    fontSize: 13, color: T.text, fontFamily: T.fontSans,
    outline: 'none', flex: 1, minWidth: 0,
    appearance: 'none', WebkitAppearance: 'none',
  }

  if (loading) return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 80 }}>
      <div style={{ color: T.textDim, fontSize: 14 }}>加载中...</div>
    </div>
  )

  return (
    <div style={{ padding: '16px 16px 0' }}>
      {/* Search */}
      <div style={{ position: 'relative', marginBottom: 12 }}>
        <input
          type="text" placeholder="搜索客户..." value={search}
          onChange={e => setSearch(e.target.value)}
          style={{
            width: '100%', padding: '10px 14px', fontSize: 14,
            background: T.bgCard, border: `1px solid ${T.border}`,
            borderRadius: T.radiusSm, color: T.text, outline: 'none',
            boxSizing: 'border-box', fontFamily: T.fontSans,
          }}
        />
        {search && (
          <button onClick={() => setSearch('')} style={{
            position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)',
            background: 'none', border: 'none', color: T.textDim, cursor: 'pointer', fontSize: 14,
          }}>✕</button>
        )}
      </div>

      {/* Filters */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <select
          value={salesFilter}
          onChange={e => setSalesFilter(e.target.value)}
          style={selectStyle}
        >
          <option value="">全部销售</option>
          {MAIN_SALES.map(s => (
            <option key={s.wechatId} value={s.wechatId}>{s.name}</option>
          ))}
        </select>

        <select
          value={tagFilter}
          onChange={e => setTagFilter(e.target.value)}
          style={selectStyle}
        >
          <option value="">全部标签</option>
          {availableTags.map(tag => (
            <option key={tag} value={tag}>{tag}</option>
          ))}
        </select>
      </div>

      {/* Count */}
      <div style={{
        fontSize: 12, color: T.textDim, marginBottom: 12,
      }}>
        共 {filtered.length} 位客户
      </div>

      {/* Customer list */}
      {filtered.map(contact => (
        <CustomerCard
          key={contact.id}
          contact={contact}
          expanded={expandedId === contact.id}
          onToggle={() => setExpandedId(expandedId === contact.id ? null : contact.id)}
        />
      ))}

      {filtered.length === 0 && (
        <div style={{ textAlign: 'center', padding: '60px 20px', color: T.textDim }}>
          <div style={{ fontSize: 40, marginBottom: 16 }}>👥</div>
          <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>没有匹配的客户</div>
          <div style={{ fontSize: 13 }}>尝试调整筛选条件</div>
        </div>
      )}
    </div>
  )
}
