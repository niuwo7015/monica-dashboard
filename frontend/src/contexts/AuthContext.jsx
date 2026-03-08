import { createContext, useContext, useState, useEffect } from 'react'
import { T, SALES_LIST } from '../lib/theme'

const AuthContext = createContext(null)

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

export function AuthProvider({ children }) {
  const [userProfile, setUserProfile] = useState(() => {
    try {
      const saved = localStorage.getItem('monica_user')
      return saved ? JSON.parse(saved) : null
    } catch { return null }
  })

  useEffect(() => {
    if (userProfile) {
      localStorage.setItem('monica_user', JSON.stringify(userProfile))
    } else {
      localStorage.removeItem('monica_user')
    }
  }, [userProfile])

  const signIn = (salesItem) => {
    setUserProfile({ name: salesItem.name, salesWechatId: salesItem.wechatId })
  }

  const signOut = () => setUserProfile(null)

  if (!userProfile) {
    return <LoginScreen onSelect={signIn} />
  }

  return (
    <AuthContext.Provider value={{ userProfile, signOut }}>
      {children}
    </AuthContext.Provider>
  )
}

function LoginScreen({ onSelect }) {
  return (
    <div style={{
      minHeight: '100vh', background: T.bg, display: 'flex',
      alignItems: 'center', justifyContent: 'center', fontFamily: T.fontSans,
    }}>
      <div style={{
        width: '100%', maxWidth: 360, padding: 32,
        background: T.bgCard, borderRadius: T.radius,
        border: `1px solid ${T.border}`,
      }}>
        <div style={{
          textAlign: 'center', marginBottom: 32,
        }}>
          <div style={{ fontSize: 36, marginBottom: 8 }}>☕</div>
          <div style={{
            fontSize: 20, fontWeight: 900, color: T.text,
            fontFamily: T.fontSerif, marginBottom: 6,
          }}>
            莫妮卡摩卡
          </div>
          <div style={{ fontSize: 13, color: T.textDim }}>
            销售工作台 · 选择你的账号
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {SALES_LIST.map(s => (
            <button
              key={s.wechatId}
              onClick={() => onSelect(s)}
              style={{
                background: T.bg, border: `1px solid ${T.border}`,
                borderRadius: T.radiusSm, padding: '14px 16px',
                color: T.text, fontSize: 15, fontWeight: 700,
                fontFamily: T.fontSans, cursor: 'pointer',
                textAlign: 'left', transition: 'all 0.2s',
              }}
              onMouseEnter={e => {
                e.currentTarget.style.borderColor = T.gold
                e.currentTarget.style.background = T.bgCard
              }}
              onMouseLeave={e => {
                e.currentTarget.style.borderColor = T.border
                e.currentTarget.style.background = T.bg
              }}
            >
              {s.name}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
