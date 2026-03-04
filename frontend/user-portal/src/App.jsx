import React from 'react'
import { BrowserRouter, Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom'
import Login from './pages/Login'
import Home from './pages/Home'
import Payment from './pages/Payment'
import OTT from './pages/OTT'
import Support from './pages/Support'

function BottomNav() {
  const navigate = useNavigate()
  const location = useLocation()

  const tabs = [
    { path: '/home', label: 'হোম', icon: '🏠' },
    { path: '/payment', label: 'পেমেন্ট', icon: '💳' },
    { path: '/ott', label: 'বিনোদন', icon: '🎬' },
    { path: '/support', label: 'সাহায্য', icon: '💬' },
  ]

  return (
    <nav className="bottom-nav">
      {tabs.map(tab => (
        <button
          key={tab.path}
          className={`nav-tab ${location.pathname === tab.path ? 'active' : ''}`}
          onClick={() => navigate(tab.path)}
        >
          <span style={{ fontSize: 20 }}>{tab.icon}</span>
          <span>{tab.label}</span>
        </button>
      ))}
    </nav>
  )
}

function ProtectedLayout({ children }) {
  const token = localStorage.getItem('whisp_sub_token')
  if (!token) return <Navigate to="/login" replace />
  return (
    <>
      {children}
      <BottomNav />
    </>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/home" element={<ProtectedLayout><Home /></ProtectedLayout>} />
        <Route path="/payment" element={<ProtectedLayout><Payment /></ProtectedLayout>} />
        <Route path="/ott" element={<ProtectedLayout><OTT /></ProtectedLayout>} />
        <Route path="/support" element={<ProtectedLayout><Support /></ProtectedLayout>} />
        <Route path="/" element={<Navigate to="/home" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
