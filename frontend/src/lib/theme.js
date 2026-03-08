/* ═══════════════════════════════════════
   Design Tokens v5 — 黑金玫瑰
   共享设计系统，所有页面统一使用
   ═══════════════════════════════════════ */

export const T = {
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

export const SALES_LIST = [
  { name: '可欣', wechatId: 'wxid_am3kdib9tt3722' },
  { name: '小杰', wechatId: 'wxid_p03xoj66oss112' },
  { name: '霄剑', wechatId: 'wxid_cbk7hkyyp11t12' },
  { name: 'Fiona', wechatId: 'wxid_aufah51bw9ok22' },
  { name: '晴天喵', wechatId: 'wxid_idjldooyihpj22' },
  { name: 'Joy', wechatId: 'wxid_rxc39paqvic522' },
]

// 3 main sales for filter dropdown
export const MAIN_SALES = SALES_LIST.slice(0, 3)

export const TASK_TYPE_INFO = {
  urgent_reply: { label: '紧急回复', action: '立即回复客户消息', color: T.red },
  follow_up_silent: { label: '沉默跟进', action: '主动跟进沉默客户', color: T.orange },
  reactivate: { label: '沉默激活', action: '重新激活长期未互动客户', color: T.gold },
  initial_contact: { label: '首次联系', action: '发起首次破冰对话', color: T.green },
}

export const PRIORITY_GROUPS = [
  { min: 10, key: 'urgent', label: '紧急', color: T.red, emoji: '🔥', desc: '客户在等你回复' },
  { min: 5, key: 'high', label: '重要', color: T.orange, emoji: '⚡', desc: '客户沉默需跟进' },
  { min: 3, key: 'medium', label: '一般', color: T.gold, emoji: '💡', desc: '长时间未互动' },
  { min: 0, key: 'low', label: '了解', color: T.green, emoji: '🌱', desc: '尚无聊天记录' },
]

export function getPriorityGroup(priority) {
  return PRIORITY_GROUPS.find(g => priority >= g.min) || PRIORITY_GROUPS[PRIORITY_GROUPS.length - 1]
}

export function parseSilentDays(triggerRule) {
  if (!triggerRule) return null
  const m = triggerRule.match(/(\d+)天/)
  return m ? parseInt(m[1], 10) : null
}

export const INJECTED_CSS = `
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
* { margin: 0; padding: 0; box-sizing: border-box; }
body { background: ${T.bg}; overflow-x: hidden; -webkit-font-smoothing: antialiased; }
`
