import React, { useState, useEffect } from 'react'

const PAYMENT_METHODS = [
  { id: 'bkash', label: 'bKash', color: '#E2136E', emoji: '📱' },
  { id: 'nagad', label: 'Nagad', color: '#DC2626', emoji: '💰' },
  { id: 'card', label: 'কার্ড/ব্যাংক', color: '#2563eb', emoji: '💳' },
]

const MOCK_PLANS = [
  { id: '1', name: 'বেসিক', speed_download_kbps: 5120, data_cap_gb: 30, validity_days: 30, price: 350, ott_chorki: false, ott_hoichoi: false },
  { id: '2', name: 'স্ট্যান্ডার্ড', speed_download_kbps: 10240, data_cap_gb: 60, validity_days: 30, price: 500, ott_chorki: true, ott_hoichoi: false },
  { id: '3', name: 'ফ্যামিলি প্লাস', speed_download_kbps: 20480, data_cap_gb: 100, validity_days: 30, price: 600, ott_chorki: true, ott_hoichoi: true },
  { id: '4', name: 'আনলিমিটেড', speed_download_kbps: 51200, data_cap_gb: 0, validity_days: 30, price: 900, ott_chorki: true, ott_hoichoi: true },
]

const MOCK_HISTORY = [
  { id: 'p1', amount: 600, gateway: 'bkash', status: 'completed', created_at: '2026-02-04T10:30:00Z', plan_name: 'ফ্যামিলি প্লাস' },
  { id: 'p2', amount: 600, gateway: 'nagad', status: 'completed', created_at: '2026-01-05T09:15:00Z', plan_name: 'ফ্যামিলি প্লাস' },
  { id: 'p3', amount: 500, gateway: 'bkash', status: 'completed', created_at: '2025-12-05T11:00:00Z', plan_name: 'স্ট্যান্ডার্ড' },
  { id: 'p4', amount: 500, gateway: 'card', status: 'failed', created_at: '2025-11-06T14:22:00Z', plan_name: 'স্ট্যান্ডার্ড' },
  { id: 'p5', amount: 350, gateway: 'bkash', status: 'completed', created_at: '2025-10-07T08:45:00Z', plan_name: 'বেসিক' },
]

function toBengaliDigits(num) {
  const bengali = ['০', '১', '২', '৩', '৪', '৫', '৬', '৭', '৮', '৯']
  return String(num).replace(/[0-9]/g, d => bengali[parseInt(d)])
}

function formatDate(dateStr) {
  const d = new Date(dateStr)
  return d.toLocaleDateString('bn-BD', { day: '2-digit', month: 'short', year: 'numeric' })
}

function StatusBadge({ status }) {
  if (status === 'completed') return <span className="badge badge-active">সম্পন্ন</span>
  if (status === 'failed') return <span className="badge badge-expired">ব্যর্থ</span>
  return <span className="badge badge-suspended">অপেক্ষমাণ</span>
}

export default function Payment() {
  const [plans, setPlans] = useState([])
  const [history, setHistory] = useState([])
  const [selectedPlan, setSelectedPlan] = useState(null)
  const [selectedMethod, setSelectedMethod] = useState('bkash')
  const [loading, setLoading] = useState(false)
  const [currentPlanId, setCurrentPlanId] = useState(null)

  useEffect(() => {
    const token = localStorage.getItem('whisp_sub_token')
    const user = JSON.parse(localStorage.getItem('whisp_sub_user') || '{}')
    setCurrentPlanId(user.plan_id || '3')

    const fetchData = async () => {
      try {
        const [plansRes, historyRes] = await Promise.all([
          fetch('/api/plans', { headers: { Authorization: `Bearer ${token}` } }),
          fetch('/api/payments', { headers: { Authorization: `Bearer ${token}` } }),
        ])
        if (plansRes.ok) {
          const pData = await plansRes.json()
          setPlans(pData.items || pData || MOCK_PLANS)
        } else {
          setPlans(MOCK_PLANS)
        }
        if (historyRes.ok) {
          const hData = await historyRes.json()
          const items = hData.items || hData || MOCK_HISTORY
          setHistory(items.slice(0, 5))
        } else {
          setHistory(MOCK_HISTORY)
        }
      } catch {
        setPlans(MOCK_PLANS)
        setHistory(MOCK_HISTORY)
      }
    }
    fetchData()
  }, [])

  const handlePayment = async () => {
    if (!selectedPlan) return
    const token = localStorage.getItem('whisp_sub_token')
    setLoading(true)
    try {
      let endpoint = '/api/payments/bkash/initiate'
      if (selectedMethod === 'nagad') endpoint = '/api/payments/nagad/initiate'
      else if (selectedMethod === 'card') endpoint = '/api/payments/sslcommerz/initiate'

      const res = await fetch(endpoint, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ plan_id: selectedPlan.id }),
      })

      const data = await res.json()
      if (data.gateway_url) {
        window.location.href = data.gateway_url
      } else {
        alert('পেমেন্ট শুরু করা যায়নি। আবার চেষ্টা করুন।')
      }
    } catch {
      alert('পেমেন্ট শুরু করা যায়নি। আবার চেষ্টা করুন।')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div>
      <div className="page-header-bar">
        <div style={{ fontSize: '20px', fontWeight: '700' }}>প্যাকেজ নবায়ন</div>
      </div>

      <div className="page-content">
        {/* Plan selection */}
        <div style={{ marginBottom: '24px' }}>
          <div style={{ fontSize: '16px', fontWeight: '600', marginBottom: '12px' }}>
            প্যাকেজ বেছে নিন
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {plans.map(plan => {
              const isCurrent = plan.id === currentPlanId
              const isSelected = selectedPlan?.id === plan.id
              return (
                <div
                  key={plan.id}
                  onClick={() => setSelectedPlan(plan)}
                  className="card"
                  style={{
                    cursor: 'pointer',
                    border: isSelected ? '2px solid #FF6B35' : '2px solid transparent',
                    padding: '16px',
                    transition: 'all 0.15s',
                    background: isSelected ? 'rgba(255,107,53,0.04)' : 'white',
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div>
                      <div style={{ fontWeight: '600', fontSize: '16px', marginBottom: '4px' }}>
                        {plan.name}
                      </div>
                      <div style={{ fontSize: '13px', color: '#6b7280' }}>
                        {toBengaliDigits(Math.round(plan.speed_download_kbps / 1024))} Mbps
                        {plan.data_cap_gb > 0 ? ` · ${toBengaliDigits(plan.data_cap_gb)} GB` : ' · আনলিমিটেড'}
                        {' · '}{toBengaliDigits(plan.validity_days)} দিন
                      </div>
                      {(plan.ott_chorki || plan.ott_hoichoi) && (
                        <div style={{ fontSize: '12px', color: '#FF6B35', marginTop: '4px' }}>
                          {[plan.ott_chorki && 'চড়কি', plan.ott_hoichoi && 'হইচই'].filter(Boolean).join(' + ')} অন্তর্ভুক্ত
                        </div>
                      )}
                    </div>
                    <div style={{ textAlign: 'right', flexShrink: 0, marginLeft: '12px' }}>
                      <div style={{ fontSize: '22px', fontWeight: '700', color: '#FF6B35' }}>
                        ৳{toBengaliDigits(plan.price)}
                      </div>
                      {isCurrent && (
                        <span className="badge badge-active" style={{ marginTop: '4px', display: 'block' }}>
                          বর্তমান
                        </span>
                      )}
                    </div>
                  </div>
                  {isSelected && (
                    <div style={{
                      marginTop: '10px',
                      width: '20px',
                      height: '20px',
                      borderRadius: '50%',
                      background: '#FF6B35',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      marginLeft: 'auto',
                    }}>
                      <span style={{ color: 'white', fontSize: '12px' }}>✓</span>
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {/* Payment method */}
        {selectedPlan && (
          <>
            <div style={{ marginBottom: '24px' }}>
              <div style={{ fontSize: '16px', fontWeight: '600', marginBottom: '12px' }}>
                পেমেন্ট পদ্ধতি
              </div>
              <div style={{ display: 'flex', gap: '10px' }}>
                {PAYMENT_METHODS.map(m => (
                  <button
                    key={m.id}
                    onClick={() => setSelectedMethod(m.id)}
                    style={{
                      flex: 1,
                      padding: '14px 8px',
                      borderRadius: '12px',
                      border: selectedMethod === m.id ? `2px solid ${m.color}` : '2px solid #e5e7eb',
                      background: selectedMethod === m.id ? m.color : 'white',
                      color: selectedMethod === m.id ? 'white' : '#1a1a2e',
                      cursor: 'pointer',
                      fontFamily: 'inherit',
                      fontSize: '13px',
                      fontWeight: '600',
                      display: 'flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      gap: '4px',
                      transition: 'all 0.15s',
                    }}
                  >
                    <span style={{ fontSize: '20px' }}>{m.emoji}</span>
                    <span>{m.label}</span>
                  </button>
                ))}
              </div>
            </div>

            <button
              className="btn-primary"
              onClick={handlePayment}
              disabled={loading}
              style={{ marginBottom: '32px' }}
            >
              {loading
                ? 'প্রক্রিয়া হচ্ছে...'
                : `পেমেন্ট করুন - ৳${toBengaliDigits(selectedPlan.price)}`}
            </button>
          </>
        )}

        {/* Payment history */}
        <div>
          <div style={{ fontSize: '16px', fontWeight: '600', marginBottom: '12px' }}>
            পেমেন্ট ইতিহাস
          </div>
          {history.length === 0 ? (
            <div className="card" style={{ textAlign: 'center', color: '#6b7280', fontSize: '14px' }}>
              কোনো পেমেন্ট নেই
            </div>
          ) : (
            <div className="card" style={{ padding: '0', overflow: 'hidden' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
                <thead>
                  <tr style={{ background: '#f4f6f8' }}>
                    <th style={{ padding: '10px 14px', textAlign: 'left', color: '#6b7280', fontWeight: '500' }}>তারিখ</th>
                    <th style={{ padding: '10px 14px', textAlign: 'left', color: '#6b7280', fontWeight: '500' }}>প্যাকেজ</th>
                    <th style={{ padding: '10px 14px', textAlign: 'right', color: '#6b7280', fontWeight: '500' }}>পরিমাণ</th>
                    <th style={{ padding: '10px 14px', textAlign: 'center', color: '#6b7280', fontWeight: '500' }}>অবস্থা</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((tx, i) => (
                    <tr key={tx.id} style={{ borderTop: i > 0 ? '1px solid #f0f0f0' : 'none' }}>
                      <td style={{ padding: '10px 14px', color: '#6b7280' }}>
                        {formatDate(tx.created_at)}
                      </td>
                      <td style={{ padding: '10px 14px' }}>{tx.plan_name}</td>
                      <td style={{ padding: '10px 14px', textAlign: 'right', fontWeight: '600' }}>
                        ৳{toBengaliDigits(tx.amount)}
                      </td>
                      <td style={{ padding: '10px 14px', textAlign: 'center' }}>
                        <StatusBadge status={tx.status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
