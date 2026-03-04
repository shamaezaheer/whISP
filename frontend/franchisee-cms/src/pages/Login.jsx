import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'

export default function Login() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const { login } = useAuth()
  const navigate = useNavigate()

  const handleSubmit = async e => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(email, password)
      navigate('/dashboard')
    } catch (err) {
      setError(err.response?.data?.detail || 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-page">
      <style>{`
        .login-page { min-height: 100vh; display: flex; align-items: center; justify-content: center; background: #0a0a0a; }
        .login-box { width: 380px; border: 1px solid #222; background: #111; padding: 40px; }
        .login-title { font-size: 22px; color: #00ff88; margin-bottom: 4px; }
        .login-sub { font-size: 12px; color: #555; margin-bottom: 32px; }
        .error-msg { color: #ff4444; font-size: 12px; margin-top: 12px; }
      `}</style>
      <div className="login-box">
        <div className="login-title">whISP</div>
        <div className="login-sub">Franchisee Management System</div>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Email</label>
            <input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="admin@franchise.com" required />
          </div>
          <div className="form-group">
            <label>Password</label>
            <input type="password" value={password} onChange={e => setPassword(e.target.value)} placeholder="••••••••" required />
          </div>
          <button type="submit" className="btn" style={{ width: '100%' }} disabled={loading}>
            {loading ? 'Authenticating...' : '→ Login'}
          </button>
          {error && <div className="error-msg">{error}</div>}
        </form>
      </div>
    </div>
  )
}
