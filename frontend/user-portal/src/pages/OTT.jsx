import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

const OTT_SERVICES = [
  {
    id: 'chorki',
    label: 'চড়কি',
    description: 'বাংলা সিনেমা ও নাটক',
    color: '#E53935',
    bg: 'rgba(229,57,53,0.08)',
    emoji: '🎬',
  },
  {
    id: 'hoichoi',
    label: 'হইচই',
    description: 'বাংলা বিনোদন',
    color: '#1565C0',
    bg: 'rgba(21,101,192,0.08)',
    emoji: '🎭',
  },
  {
    id: 'binge',
    label: 'বিঞ্জ',
    description: 'রোবি বিনোদন',
    color: '#F57C00',
    bg: 'rgba(245,124,0,0.08)',
    emoji: '📺',
  },
  {
    id: 'toffee',
    label: 'টফি',
    description: 'বাংলালিংক বিনোদন',
    color: '#7B1FA2',
    bg: 'rgba(123,31,162,0.08)',
    emoji: '🍬',
  },
]

const MOCK_ENTITLEMENTS = [
  { partner: 'chorki', active: true },
  { partner: 'hoichoi', active: true },
  { partner: 'binge', active: false },
  { partner: 'toffee', active: false },
]

export default function OTT() {
  const navigate = useNavigate()
  const [entitlements, setEntitlements] = useState({})
  const [launching, setLaunching] = useState(null)

  useEffect(() => {
    const token = localStorage.getItem('whisp_sub_token')
    const fetchEntitlements = async () => {
      try {
        const res = await fetch('/api/ott/entitlements', {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (res.ok) {
          const data = await res.json()
          const map = {}
          const items = data.items || data || MOCK_ENTITLEMENTS
          items.forEach(e => {
            map[e.partner] = e.active
          })
          setEntitlements(map)
        } else {
          const map = {}
          MOCK_ENTITLEMENTS.forEach(e => { map[e.partner] = e.active })
          setEntitlements(map)
        }
      } catch {
        const map = {}
        MOCK_ENTITLEMENTS.forEach(e => { map[e.partner] = e.active })
        setEntitlements(map)
      }
    }
    fetchEntitlements()
  }, [])

  const handleLaunch = async (partner) => {
    const token = localStorage.getItem('whisp_sub_token')
    setLaunching(partner)
    try {
      const res = await fetch(`/api/ott/launch/${partner}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (res.ok) {
        const data = await res.json()
        if (data.sso_url) {
          window.open(data.sso_url, '_blank', 'noopener')
        } else {
          alert('লিংক পাওয়া যায়নি। আবার চেষ্টা করুন।')
        }
      } else {
        alert('সেবাটি এই মুহূর্তে উপলব্ধ নয়।')
      }
    } catch {
      alert('সংযোগ সমস্যা। আবার চেষ্টা করুন।')
    } finally {
      setLaunching(null)
    }
  }

  return (
    <div>
      <div className="page-header-bar">
        <div>
          <div style={{ fontSize: '20px', fontWeight: '700' }}>বিনোদন</div>
          <div style={{ fontSize: '13px', opacity: 0.85, marginTop: '2px' }}>
            আপনার প্যানেলে অন্তর্ভুক্ত সেবা
          </div>
        </div>
      </div>

      <div className="page-content">
        <div style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: '14px',
          marginBottom: '24px',
        }}>
          {OTT_SERVICES.map(svc => {
            const isActive = entitlements[svc.id] === true
            const isLoading = launching === svc.id

            return (
              <div
                key={svc.id}
                className="card"
                style={{
                  padding: '18px 14px',
                  textAlign: 'center',
                  border: isActive ? `2px solid ${svc.color}` : '2px solid #e5e7eb',
                  opacity: isActive ? 1 : 0.7,
                  background: isActive ? svc.bg : 'white',
                }}
              >
                <div style={{ fontSize: '32px', marginBottom: '8px' }}>{svc.emoji}</div>
                <div style={{
                  fontSize: '17px',
                  fontWeight: '700',
                  color: isActive ? svc.color : '#6b7280',
                  marginBottom: '4px',
                }}>
                  {svc.label}
                </div>
                <div style={{ fontSize: '12px', color: '#6b7280', marginBottom: '12px' }}>
                  {svc.description}
                </div>

                {isActive ? (
                  <>
                    <div style={{ marginBottom: '10px' }}>
                      <span className="badge badge-active">সক্রিয়</span>
                    </div>
                    <button
                      onClick={() => handleLaunch(svc.id)}
                      disabled={isLoading}
                      style={{
                        background: svc.color,
                        color: 'white',
                        border: 'none',
                        borderRadius: '8px',
                        padding: '9px 14px',
                        fontSize: '13px',
                        fontWeight: '600',
                        cursor: isLoading ? 'not-allowed' : 'pointer',
                        fontFamily: 'inherit',
                        width: '100%',
                        opacity: isLoading ? 0.7 : 1,
                        transition: 'opacity 0.15s',
                      }}
                    >
                      {isLoading ? '...' : 'এখনই দেখুন →'}
                    </button>
                  </>
                ) : (
                  <>
                    <div style={{ marginBottom: '10px' }}>
                      <span className="badge" style={{ background: '#f4f6f8', color: '#6b7280' }}>
                        অন্তর্ভুক্ত নয়
                      </span>
                    </div>
                    <button
                      onClick={() => navigate('/payment')}
                      style={{
                        background: 'transparent',
                        color: '#6b7280',
                        border: '1.5px solid #e5e7eb',
                        borderRadius: '8px',
                        padding: '9px 14px',
                        fontSize: '13px',
                        fontWeight: '500',
                        cursor: 'pointer',
                        fontFamily: 'inherit',
                        width: '100%',
                        transition: 'all 0.15s',
                      }}
                    >
                      আপগ্রেড করুন
                    </button>
                  </>
                )}
              </div>
            )
          })}
        </div>

        {/* Info card */}
        <div className="card" style={{
          background: 'rgba(255,107,53,0.06)',
          border: '1px solid rgba(255,107,53,0.2)',
        }}>
          <div style={{ fontSize: '14px', color: '#92400e', lineHeight: '1.6' }}>
            <strong>দ্রষ্টব্য:</strong> OTT সেবাসমূহ আপনার ইন্টারনেট প্যাকেজের সাথে অন্তর্ভুক্ত।
            উচ্চতর প্যাকেজে আপগ্রেড করে আরও সেবা উপভোগ করুন।
          </div>
        </div>
      </div>
    </div>
  )
}
