import React from 'react'
import { BrowserRouter, Routes, Route, Navigate, NavLink, useNavigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './hooks/useAuth'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Subscribers from './pages/Subscribers'
import Plans from './pages/Plans'
import Billing from './pages/Billing'
import Usage from './pages/Usage'
import Devices from './pages/Devices'
import Tickets from './pages/Tickets'

function ProtectedRoute({ children }) {
  const { isAuthenticated } = useAuth()
  return isAuthenticated ? children : <Navigate to="/login" replace />
}

function Sidebar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

  const nav = [
    { path: '/dashboard', label: 'Dashboard', icon: '◈' },
    { path: '/subscribers', label: 'Subscribers', icon: '◉' },
    { path: '/plans', label: 'Plans', icon: '◇' },
    { path: '/usage', label: 'Usage', icon: '▲' },
    { path: '/billing', label: 'Billing', icon: '◆' },
    { path: '/devices', label: 'Devices', icon: '▣' },
    { path: '/tickets', label: 'Tickets', icon: '◎' },
  ]

  return (
    <div className="sidebar">
      <div className="sidebar-logo">
        whISP<span>CMS v1.0</span>
      </div>
      <nav className="sidebar-nav">
        {nav.map(item => (
          <NavLink
            key={item.path}
            to={item.path}
            className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
          >
            <span>{item.icon}</span>
            <span>{item.label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="sidebar-footer">
        <div className="text-muted" style={{ fontSize: 11, marginBottom: 8 }}>
          {user?.email}
        </div>
        <button className="btn btn-ghost btn-sm" style={{ width: '100%' }} onClick={() => { logout(); navigate('/login') }}>
          Logout
        </button>
      </div>
    </div>
  )
}

function Layout({ children }) {
  return (
    <div className="layout">
      <Sidebar />
      <main className="main-content">{children}</main>
    </div>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/*" element={
            <ProtectedRoute>
              <Layout>
                <Routes>
                  <Route path="/dashboard" element={<Dashboard />} />
                  <Route path="/subscribers" element={<Subscribers />} />
                  <Route path="/plans" element={<Plans />} />
                  <Route path="/usage" element={<Usage />} />
                  <Route path="/billing" element={<Billing />} />
                  <Route path="/devices" element={<Devices />} />
                  <Route path="/tickets" element={<Tickets />} />
                  <Route path="/" element={<Navigate to="/dashboard" replace />} />
                </Routes>
              </Layout>
            </ProtectedRoute>
          } />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
