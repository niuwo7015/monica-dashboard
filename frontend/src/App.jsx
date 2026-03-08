import { Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { useEffect } from 'react'
import { T, INJECTED_CSS } from './lib/theme'
import { useAuth } from './contexts/AuthContext'
import SalesToday from './pages/SalesToday'
import CustomerList from './pages/CustomerList'
import Dashboard from './pages/Dashboard'

const TABS = [
  { path: '/today', label: '今日任务', emoji: '📋' },
  { path: '/customers', label: '客户列表', emoji: '👥' },
  { path: '/dashboard', label: '数据看板', emoji: '📊' },
]

function useInjectCSS() {
  useEffect(() => {
    const id = 'monica-global-css'
    if (!document.getElementById(id)) {
      const s = document.createElement('style')
      s.id = id
      s.textContent = INJECTED_CSS
      document.head.appendChild(s)
    }
  }, [])
}

export default function App() {
  useInjectCSS()
  const { userProfile, signOut } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()

  return (
    <div style={{
      minHeight: '100vh', background: T.bg,
      fontFamily: T.fontSans, color: T.text,
      maxWidth: 640, margin: '0 auto',
      paddingBottom: 64,
    }}>
      {/* Top bar */}
      <div style={{
        position: 'sticky', top: 0, zIndex: 100,
        background: 'rgba(20,18,20,0.92)', backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        padding: '10px 16px',
        borderBottom: `1px solid ${T.border}`,
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      }}>
        <span style={{
          fontSize: 15, fontWeight: 900, color: T.text,
          fontFamily: T.fontSerif,
        }}>
          ☕ 莫妮卡摩卡 · {userProfile?.name}
        </span>
        <button onClick={signOut} style={{
          background: 'none', border: `1px solid ${T.border}`, borderRadius: 8,
          color: T.textSub, padding: '4px 12px', fontSize: 12,
          cursor: 'pointer', fontFamily: T.fontSans,
        }}>退出</button>
      </div>

      {/* Page content */}
      <Routes>
        <Route path="/today" element={<SalesToday />} />
        <Route path="/customers" element={<CustomerList />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="*" element={<Navigate to="/today" replace />} />
      </Routes>

      {/* Bottom tab bar */}
      <div style={{
        position: 'fixed', bottom: 0, left: '50%', transform: 'translateX(-50%)',
        width: '100%', maxWidth: 640,
        background: 'rgba(20,18,20,0.95)', backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        borderTop: `1px solid ${T.border}`,
        display: 'flex', justifyContent: 'space-around',
        padding: '6px 0 env(safe-area-inset-bottom, 6px)',
        zIndex: 100,
      }}>
        {TABS.map(tab => {
          const active = location.pathname === tab.path
          return (
            <button
              key={tab.path}
              onClick={() => navigate(tab.path)}
              style={{
                background: 'none', border: 'none',
                display: 'flex', flexDirection: 'column', alignItems: 'center',
                gap: 2, padding: '6px 12px',
                cursor: 'pointer', transition: 'all 0.2s',
              }}
            >
              <span style={{ fontSize: 18 }}>{tab.emoji}</span>
              <span style={{
                fontSize: 11, fontWeight: 600,
                color: active ? T.gold : T.textDim,
                fontFamily: T.fontSans,
              }}>
                {tab.label}
              </span>
              {active && (
                <div style={{
                  width: 4, height: 4, borderRadius: '50%',
                  background: T.gold, marginTop: 1,
                }} />
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
