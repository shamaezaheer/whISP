import React, { useState, useEffect, useCallback } from 'react'
import axios from 'axios'

const MOCK_PAYMENTS = [
  {
    id: 1, date: '2026-03-04 09:14', subscriber: 'client001', name: 'Rahim Uddin',
    amount: 600, gateway: 'bKash', status: 'completed', ref: 'BK202603040001'
  },
  {
    id: 2, date: '2026-03-04 08:55', subscriber: 'client003', name: 'Nasrin Begum',
    amount: 1500, gateway: 'Nagad', status: 'completed', ref: 'NG202603040001'
  },
  {
    id: 3, date: '2026-03-04 08:22', subscriber: 'client006', name: 'Monir Hossain',
    amount: 900, gateway: 'SSLCommerz', status: 'completed', ref: 'SSL20260304001'
  },
  {
    id: 4, date: '2026-03-04 07:45', subscriber: 'client011', name: 'Karim Hossain',
    amount: 900, gateway: 'bKash', status: 'pending', ref: 'BK202603040002'
  },
  {
    id: 5, date: '2026-03-03 22:10', subscriber: 'client019', name: 'Farhana Islam',
    amount: 2500, gateway: 'Manual', status: 'completed', ref: 'MAN20260303001'
  },
  {
    id: 6, date: '2026-03-03 18:33', subscriber: 'client027', name: 'Sabbir Ahmed',
    amount: 600, gateway: 'bKash', status: 'failed', ref: 'BK202603030003'
  },
  {
    id: 7, date: '2026-03-03 14:02', subscriber: 'client034', name: 'Taslima Khatun',
    amount: 1500, gateway: 'Nagad', status: 'completed', ref: 'NG202603030002'
  },
  {
    id: 8, date: '2026-03-03 11:19', subscriber: 'client047', name: 'Habib Rahman',
    amount: 900, gateway: 'SSLCommerz', status: 'completed', ref: 'SSL20260303002'
  },
  {
    id: 9, date: '2026-03-02 16:44', subscriber: 'client015', name: 'Jalal Uddin',
    amount: 2500, gateway: 'Manual', status: 'completed', ref: 'MAN20260302001'
  },
  {
    id: 10, date: '2026-03-02 10:31', subscriber: 'client062', name: 'Rehana Parvin',
    amount: 600, gateway: 'bKash', status: 'pending', ref: 'BK202603020001'
  },
]

const GATEWAY_BADGE = {
  bKash: { bg: 'rgba(0,200,80,0.1)', color: '#00c850', border: 'rgba(0,200,80,0.3)' },
  Nagad: { bg: 'rgba(255,68,0,0.1)', color: '#ff4400', border: 'rgba(255,68,0,0.3)' },
  SSLCommerz: { bg: 'rgba(0,136,255,0.1)', color: '#0088ff', border: 'rgba(0,136,255,0.3)' },
  Manual: { bg: 'rgba(100,100,100,0.15)', color: '#888888', border: '#444444' },
}

function GatewayBadge({ gateway }) {
  const style = GATEWAY_BADGE[gateway] || GATEWAY_BADGE.Manual
  return (
    <span style={{
      display: 'inline-block', padding: '2px 8px', fontSize: 11,
      background: style.bg, color: style.color,
      border: `1px solid ${style.border}`
    }}>
      {gateway}
    </span>
  )
}

function StatusBadge({ status }) {
  const cls = {
    completed: 'badge-active',
    failed: 'badge-suspended',
    pending: 'badge-pending',
  }[status] || 'badge-pending'
  return <span className={`badge ${cls}`}>{status}</span>
}

export default function Billing() {
  const [payments, setPayments] = useState(MOCK_PAYMENTS)
  const [loading, setLoading] = useState(false)
  const [apiError, setApiError] = useState(false)
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const fetchPayments = useCallback(async () => {
    setLoading(true)
    try {
      const params = {}
      if (dateFrom) params.from = dateFrom
      if (dateTo) params.to = dateTo
      const res = await axios.get('/api/payments', { params })
      setPayments(res.data?.items || res.data?.payments || MOCK_PAYMENTS)
      setApiError(false)
    } catch {
      setApiError(true)
    } finally {
      setLoading(false)
    }
  }, [dateFrom, dateTo])

  useEffect(() => { fetchPayments() }, [fetchPayments])

  // Revenue summaries from current data
  const today = new Date().toISOString().slice(0, 10)
  const thisMonth = today.slice(0, 7)

  const todayTotal = payments
    .filter(p => p.status === 'completed' && p.date.startsWith(today))
    .reduce((sum, p) => sum + p.amount, 0)

  const monthTotal = payments
    .filter(p => p.status === 'completed' && p.date.startsWith(thisMonth))
    .reduce((sum, p) => sum + p.amount, 0)

  const outstanding = payments
    .filter(p => p.status === 'pending')
    .reduce((sum, p) => sum + p.amount, 0)

  return (
    <div>
      <div className="page-header">
        <div className="page-title">Billing</div>
        {apiError && <span style={{ fontSize: 11, color: '#ffaa00' }}>Mock data</span>}
      </div>

      <div className="page-body">
        {/* Revenue Summary */}
        <div className="stat-grid mb-6">
          <div className="stat-card">
            <div className="stat-label">Today's Revenue</div>
            <div className="stat-value">৳{todayTotal.toLocaleString()}</div>
            <div className="stat-sub">{today}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">This Month</div>
            <div className="stat-value">৳{monthTotal.toLocaleString()}</div>
            <div className="stat-sub">{thisMonth}</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Outstanding</div>
            <div className="stat-value" style={{ color: outstanding > 0 ? '#ffaa00' : '#00ff88' }}>
              ৳{outstanding.toLocaleString()}
            </div>
            <div className="stat-sub">pending payments</div>
          </div>
        </div>

        {/* Filters */}
        <div className="flex gap-2 mb-4 items-center">
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <label style={{ marginBottom: 0, whiteSpace: 'nowrap' }}>From</label>
            <input
              type="text"
              value={dateFrom}
              onChange={e => setDateFrom(e.target.value)}
              placeholder="2026-03-01"
              style={{ width: 130 }}
            />
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <label style={{ marginBottom: 0, whiteSpace: 'nowrap' }}>To</label>
            <input
              type="text"
              value={dateTo}
              onChange={e => setDateTo(e.target.value)}
              placeholder="2026-03-31"
              style={{ width: 130 }}
            />
          </div>
          <button className="btn btn-sm" onClick={fetchPayments}>Apply</button>
          <button className="btn btn-sm btn-ghost" onClick={() => { setDateFrom(''); setDateTo('') }}>Clear</button>
        </div>

        {/* Transactions table */}
        {loading ? (
          <div className="text-muted" style={{ padding: 24 }}>Loading...</div>
        ) : (
          <div className="card">
            <div style={{ overflowX: 'auto' }}>
              <table>
                <thead>
                  <tr>
                    <th>Date / Time</th>
                    <th>Subscriber</th>
                    <th>Amount (BDT)</th>
                    <th>Gateway</th>
                    <th>Status</th>
                    <th>Reference</th>
                  </tr>
                </thead>
                <tbody>
                  {payments.map(p => (
                    <tr key={p.id}>
                      <td className="text-muted" style={{ fontSize: 11 }}>{p.date}</td>
                      <td>
                        <div className="text-accent" style={{ fontSize: 12 }}>{p.subscriber}</div>
                        <div className="text-muted" style={{ fontSize: 10 }}>{p.name}</div>
                      </td>
                      <td style={{ fontWeight: 600, color: p.status === 'failed' ? '#ff4444' : '#00ff88' }}>
                        ৳{p.amount.toLocaleString()}
                      </td>
                      <td><GatewayBadge gateway={p.gateway} /></td>
                      <td><StatusBadge status={p.status} /></td>
                      <td className="text-muted" style={{ fontSize: 10 }}>{p.ref}</td>
                    </tr>
                  ))}
                  {payments.length === 0 && (
                    <tr>
                      <td colSpan={6} style={{ textAlign: 'center', color: '#555', padding: 32 }}>
                        No transactions found
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
