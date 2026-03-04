import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'

export default function Login() {
  const navigate = useNavigate()
  const [phone, setPhone] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleLogin = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: phone,
          password,
          actor_type: 'subscriber',
        }),
      })

      const data = await res.json()

      if (!res.ok) {
        setError('ভুল তথ্য দেওয়া হয়েছে')
        return
      }

      localStorage.setItem('whisp_sub_token', data.access_token)
      localStorage.setItem('whisp_sub_user', JSON.stringify(data.user || data))
      navigate('/home')
    } catch (err) {
      setError('ভুল তথ্য দেওয়া হয়েছে')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh',
      background: 'linear-gradient(135deg, #FF6B35 0%, #e55a2b 60%, #c94820 100%)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '24px 16px',
    }}>
      <div style={{
        background: 'white',
        borderRadius: '24px',
        padding: '36px 28px',
        width: '100%',
        maxWidth: '400px',
        boxShadow: '0 20px 60px rgba(0,0,0,0.2)',
      }}>
        {/* Logo / Title */}
        <div style={{ textAlign: 'center', marginBottom: '32px' }}>
          <div style={{
            fontSize: '42px',
            fontWeight: '700',
            color: '#FF6B35',
            lineHeight: 1.1,
            letterSpacing: '-1px',
          }}>
            নেটবন্ধু
          </div>
          <div style={{ fontSize: '15px', color: '#6b7280', marginTop: '6px' }}>
            আপনার ইন্টারনেট সেবা
          </div>
        </div>

        <form onSubmit={handleLogin}>
          {/* Phone field */}
          <div style={{ marginBottom: '16px' }}>
            <label>মোবাইল নম্বর</label>
            <div style={{ display: 'flex', gap: '8px' }}>
              <div style={{
                border: '2px solid #e5e7eb',
                borderRadius: '10px',
                padding: '14px 12px',
                background: '#f4f6f8',
                color: '#6b7280',
                fontSize: '15px',
                whiteSpace: 'nowrap',
                flexShrink: 0,
              }}>
                +880
              </div>
              <input
                type="tel"
                placeholder="01XXXXXXXXX"
                value={phone}
                onChange={e => setPhone(e.target.value)}
                required
                autoComplete="tel"
                style={{ flex: 1 }}
              />
            </div>
          </div>

          {/* Password field */}
          <div style={{ marginBottom: '24px' }}>
            <label>পাসওয়ার্ড</label>
            <input
              type="password"
              placeholder="আপনার পাসওয়ার্ড"
              value={password}
              onChange={e => setPassword(e.target.value)}
              required
              autoComplete="current-password"
            />
          </div>

          {/* Error */}
          {error && (
            <div style={{
              background: 'rgba(239,68,68,0.08)',
              border: '1px solid rgba(239,68,68,0.25)',
              borderRadius: '10px',
              padding: '12px 16px',
              color: '#ef4444',
              fontSize: '14px',
              marginBottom: '20px',
              textAlign: 'center',
            }}>
              {error}
            </div>
          )}

          <button
            type="submit"
            className="btn-primary"
            disabled={loading}
          >
            {loading ? 'অপেক্ষা করুন...' : 'প্রবেশ করুন'}
          </button>
        </form>

        <div style={{
          marginTop: '20px',
          textAlign: 'center',
          fontSize: '13px',
          color: '#9ca3af',
        }}>
          সমস্যা হলে আপনার ISP-এ যোগাযোগ করুন
        </div>
      </div>
    </div>
  )
}
