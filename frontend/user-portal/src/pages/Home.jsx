import React, { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'

const MOCK_DATA = {
  name: 'রাহেলা বেগম',
  plan_name: 'ফ্যামিলি প্লাস',
  speed_mbps: 20,
  price: 600,
  data_cap_bytes: 107374182400, // 100 GB
  data_used_bytes: 78442496614, // ~73%
  plan_expires_at: new Date(Date.now() + 5 * 24 * 60 * 60 * 1000).toISOString(),
  status: 'active',
}

function toBengaliDigits(num) {
  const bengali = ['০', '১', '২', '৩', '৪', '৫', '৬', '৭', '৮', '৯']
  return String(num).replace(/[0-9]/g, d => bengali[parseInt(d)])
}

function formatGB(bytes) {
  return (bytes / 1_073_741_824).toFixed(2)
}

function formatDateBN(dateStr) {
  const d = new Date(dateStr)
  const months = ['জানু', 'ফেব্রু', 'মার্চ', 'এপ্রিল', 'মে', 'জুন',
    'জুলাই', 'আগস্ট', 'সেপ্টেম্বর', 'অক্টোবর', 'নভেম্বর', 'ডিসেম্বর']
  return `${toBengaliDigits(d.getDate())} ${months[d.getMonth()]} ${toBengaliDigits(d.getFullYear())}`
}

function daysUntil(dateStr) {
  const diff = new Date(dateStr) - new Date()
  return Math.ceil(diff / (1000 * 60 * 60 * 24))
}

function QuotaRing({ pct }) {
  const radius = 110
  const stroke = 14
  const norm = radius - stroke / 2
  const circumference = 2 * Math.PI * norm
  const [offset, setOffset] = useState(circumference)
  const mounted = useRef(false)

  useEffect(() => {
    if (!mounted.current) {
      mounted.current = true
      // Trigger animation after mount
      const t = setTimeout(() => {
        setOffset(circumference * (1 - pct / 100))
      }, 100)
      return () => clearTimeout(t)
    }
  }, [pct, circumference])

  const color = pct < 60 ? '#10b981' : pct < 85 ? '#FF6B35' : '#ef4444'

  return (
    <svg width={radius * 2} height={radius * 2} style={{ display: 'block', margin: '0 auto' }}>
      {/* Track */}
      <circle
        cx={radius}
        cy={radius}
        r={norm}
        fill="none"
        stroke="#e5e7eb"
        strokeWidth={stroke}
      />
      {/* Progress */}
      <circle
        cx={radius}
        cy={radius}
        r={norm}
        fill="none"
        stroke={color}
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        transform={`rotate(-90 ${radius} ${radius})`}
        style={{ transition: 'stroke-dashoffset 1s ease-out, stroke 0.3s' }}
      />
      {/* Center text */}
      <text
        x={radius}
        y={radius - 8}
        textAnchor="middle"
        fontSize="32"
        fontWeight="700"
        fill={color}
        fontFamily="'Hind Siliguri', sans-serif"
      >
        {toBengaliDigits(Math.round(pct))}%
      </text>
      <text
        x={radius}
        y={radius + 18}
        textAnchor="middle"
        fontSize="14"
        fill="#6b7280"
        fontFamily="'Hind Siliguri', sans-serif"
      >
        ব্যবহৃত
      </text>
    </svg>
  )
}

export default function Home() {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const user = JSON.parse(localStorage.getItem('whisp_sub_user') || '{}')
    const token = localStorage.getItem('whisp_sub_token')

    const fetchUsage = async () => {
      try {
        const res = await fetch(`/api/usage/subscriber/${user.id}`, {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (res.ok) {
          const json = await res.json()
          setData(json)
        } else {
          setData({ ...MOCK_DATA, name: user.name || MOCK_DATA.name })
        }
      } catch {
        setData({ ...MOCK_DATA, name: user.name || MOCK_DATA.name })
      } finally {
        setLoading(false)
      }
    }

    fetchUsage()
  }, [])

  const handleLogout = () => {
    localStorage.removeItem('whisp_sub_token')
    localStorage.removeItem('whisp_sub_user')
    navigate('/login')
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
        <div style={{ color: '#FF6B35', fontSize: '18px' }}>লোড হচ্ছে...</div>
      </div>
    )
  }

  const usedBytes = data?.data_used_bytes ?? MOCK_DATA.data_used_bytes
  const capBytes = data?.data_cap_bytes ?? MOCK_DATA.data_cap_bytes
  const pct = capBytes > 0 ? Math.min(100, (usedBytes / capBytes) * 100) : 0
  const remainingBytes = Math.max(0, capBytes - usedBytes)
  const expiresAt = data?.plan_expires_at ?? MOCK_DATA.plan_expires_at
  const daysLeft = daysUntil(expiresAt)
  const name = data?.name ?? MOCK_DATA.name
  const planName = data?.plan_name ?? MOCK_DATA.plan_name
  const speedMbps = data?.speed_mbps ?? MOCK_DATA.speed_mbps
  const price = data?.price ?? MOCK_DATA.price

  return (
    <div>
      {/* Header */}
      <div className="page-header-bar">
        <div>
          <div style={{ fontSize: '20px', fontWeight: '700' }}>নেটবন্ধু</div>
          <div style={{ fontSize: '13px', opacity: 0.85, marginTop: '2px' }}>
            স্বাগতম, {name}!
          </div>
        </div>
        <button
          onClick={handleLogout}
          style={{
            background: 'rgba(255,255,255,0.2)',
            border: 'none',
            color: 'white',
            padding: '8px 14px',
            borderRadius: '8px',
            cursor: 'pointer',
            fontSize: '13px',
            fontFamily: 'inherit',
          }}
        >
          বের হন
        </button>
      </div>

      <div className="page-content">
        {/* Expiry warning */}
        {daysLeft <= 3 && daysLeft >= 0 && (
          <div style={{
            background: 'rgba(245,158,11,0.12)',
            border: '1px solid rgba(245,158,11,0.35)',
            borderRadius: '12px',
            padding: '14px 16px',
            marginBottom: '20px',
            fontSize: '14px',
            color: '#92400e',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}>
            <span style={{ fontSize: '18px' }}>⚠</span>
            <span>
              আপনার প্যাকেজের মেয়াদ{' '}
              <strong>{toBengaliDigits(daysLeft)} দিনে</strong> শেষ হবে!
            </span>
          </div>
        )}

        {/* Quota ring card */}
        <div className="card" style={{ marginBottom: '16px', textAlign: 'center' }}>
          <div style={{ marginBottom: '4px', color: '#6b7280', fontSize: '13px' }}>
            ডেটা ব্যবহার
          </div>
          <div style={{ padding: '16px 0 12px' }}>
            <QuotaRing pct={pct} />
          </div>
          <div style={{ fontSize: '22px', fontWeight: '700', color: '#1a1a2e' }}>
            বাকি {toBengaliDigits(formatGB(remainingBytes))} GB
          </div>
          <div style={{ fontSize: '14px', color: '#6b7280', marginTop: '6px' }}>
            মেয়াদ শেষ: {formatDateBN(expiresAt)}
          </div>
        </div>

        {/* Plan info card */}
        <div className="card" style={{ marginBottom: '20px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
            <div style={{ fontWeight: '600', fontSize: '17px' }}>{planName}</div>
            <span className="badge badge-active">সক্রিয়</span>
          </div>
          <div style={{ display: 'flex', gap: '16px' }}>
            <div style={{ flex: 1, background: '#f4f6f8', borderRadius: '10px', padding: '12px', textAlign: 'center' }}>
              <div style={{ fontSize: '20px', fontWeight: '700', color: '#FF6B35' }}>
                {toBengaliDigits(speedMbps)}
              </div>
              <div style={{ fontSize: '12px', color: '#6b7280' }}>Mbps</div>
            </div>
            <div style={{ flex: 1, background: '#f4f6f8', borderRadius: '10px', padding: '12px', textAlign: 'center' }}>
              <div style={{ fontSize: '20px', fontWeight: '700', color: '#FF6B35' }}>
                {toBengaliDigits(formatGB(capBytes))}
              </div>
              <div style={{ fontSize: '12px', color: '#6b7280' }}>GB ডেটা</div>
            </div>
            <div style={{ flex: 1, background: '#f4f6f8', borderRadius: '10px', padding: '12px', textAlign: 'center' }}>
              <div style={{ fontSize: '20px', fontWeight: '700', color: '#FF6B35' }}>
                ৳{toBengaliDigits(price)}
              </div>
              <div style={{ fontSize: '12px', color: '#6b7280' }}>মাসিক</div>
            </div>
          </div>
        </div>

        <button
          className="btn-primary"
          onClick={() => navigate('/payment')}
        >
          প্যাকেজ নবায়ন করুন
        </button>
      </div>
    </div>
  )
}
