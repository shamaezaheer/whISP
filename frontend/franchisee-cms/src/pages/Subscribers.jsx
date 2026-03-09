import React, { useState, useEffect, useCallback } from 'react'
import axios from 'axios'

const MOCK_PLANS = [
  { id: 1, name: '10 Mbps Home' },
  { id: 2, name: '20 Mbps Home' },
  { id: 3, name: '50 Mbps Office' },
  { id: 4, name: '100 Mbps Premium' },
]

const MOCK_SUBSCRIBERS = [
  {
    id: 1, username: 'client001', name: 'Rahim Uddin', phone: '01711000001',
    plan: '10 Mbps Home', status: 'active', quota_gb: 50, used_gb: 12.3,
    expiry: '2026-03-31'
  },
  {
    id: 2, username: 'client002', name: 'Karim Hossain', phone: '01722000002',
    plan: '20 Mbps Home', status: 'suspended', quota_gb: 100, used_gb: 87.4,
    expiry: '2026-03-15'
  },
  {
    id: 3, username: 'client003', name: 'Nasrin Begum', phone: '01733000003',
    plan: '50 Mbps Office', status: 'active', quota_gb: 200, used_gb: 48.2,
    expiry: '2026-04-10'
  },
  {
    id: 4, username: 'client004', name: 'Sabbir Ahmed', phone: '01744000004',
    plan: '10 Mbps Home', status: 'expired', quota_gb: 50, used_gb: 50,
    expiry: '2026-02-28'
  },
  {
    id: 5, username: 'client005', name: 'Farhana Islam', phone: '01755000005',
    plan: '100 Mbps Premium', status: 'pending', quota_gb: 500, used_gb: 0,
    expiry: '2026-04-01'
  },
  {
    id: 6, username: 'client006', name: 'Monir Hossain', phone: '01766000006',
    plan: '20 Mbps Home', status: 'active', quota_gb: 100, used_gb: 33.1,
    expiry: '2026-03-20'
  },
]

const STATUS_FILTERS = ['All', 'Active', 'Suspended', 'Expired', 'Pending']

function StatusBadge({ status }) {
  const cls = {
    active: 'badge-active',
    suspended: 'badge-suspended',
    expired: 'badge-expired',
    pending: 'badge-pending',
    terminated: 'badge-terminated',
  }[status] || 'badge-pending'
  return <span className={`badge ${cls}`}>{status}</span>
}

function QuotaBar({ used, total }) {
  if (!total) return <span className="text-muted">Unlimited</span>
  const pct = Math.min(100, (used / total) * 100)
  const cls = pct >= 90 ? 'danger' : pct >= 70 ? 'warning' : ''
  return (
    <div>
      <div className="progress" style={{ marginBottom: 3 }}>
        <div className={`progress-bar ${cls}`} style={{ width: `${pct}%` }} />
      </div>
      <span style={{ fontSize: 10, color: '#888' }}>
        {used.toFixed(1)} / {total} GB
      </span>
    </div>
  )
}

function AddModal({ plans, onClose, onSave }) {
  const [form, setForm] = useState({
    name: '', email: '', phone: '', username: '', password: '', plan_id: plans[0]?.id || ''
  })
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const handleSubmit = async e => {
    e.preventDefault()
    setSaving(true)
    setErr('')
    try {
      await onSave(form)
      onClose()
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Failed to create subscriber')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span>Add Subscriber</span>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>✕</button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            <div className="grid-2">
              <div className="form-group">
                <label>Full Name</label>
                <input type="text" value={form.name} onChange={e => set('name', e.target.value)} required placeholder="Rahim Uddin" />
              </div>
              <div className="form-group">
                <label>Phone</label>
                <input type="text" value={form.phone} onChange={e => set('phone', e.target.value)} placeholder="01711000000" />
              </div>
            </div>
            <div className="form-group">
              <label>Email</label>
              <input type="email" value={form.email} onChange={e => set('email', e.target.value)} placeholder="user@example.com" />
            </div>
            <div className="grid-2">
              <div className="form-group">
                <label>Username (PPPoE)</label>
                <input type="text" value={form.username} onChange={e => set('username', e.target.value)} required placeholder="client007" />
              </div>
              <div className="form-group">
                <label>Password</label>
                <input type="password" value={form.password} onChange={e => set('password', e.target.value)} required placeholder="••••••••" />
              </div>
            </div>
            <div className="form-group">
              <label>Plan</label>
              <select value={form.plan_id} onChange={e => set('plan_id', e.target.value)} required>
                {plans.map(p => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>
            {err && <div style={{ color: '#ff4444', fontSize: 12 }}>{err}</div>}
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn" disabled={saving}>
              {saving ? 'Creating...' : 'Create Subscriber'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function Subscribers() {
  const [subscribers, setSubscribers] = useState(MOCK_SUBSCRIBERS)
  const [plans, setPlans] = useState(MOCK_PLANS)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('All')
  const [showModal, setShowModal] = useState(false)
  const [apiError, setApiError] = useState(false)
  const [loading, setLoading] = useState(false)
  const [confirmSuspend, setConfirmSuspend] = useState(null)

  const fetchSubscribers = useCallback(async () => {
    setLoading(true)
    try {
      const res = await axios.get('/api/subscribers')
      const data = res.data?.items ?? res.data?.subscribers ?? res.data
      setSubscribers(Array.isArray(data) ? data : MOCK_SUBSCRIBERS)
      setApiError(false)
    } catch {
      setApiError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchPlans = useCallback(async () => {
    try {
      const res = await axios.get('/api/plans')
      setPlans(res.data?.items || res.data?.plans || MOCK_PLANS)
    } catch {
      // keep mock
    }
  }, [])

  useEffect(() => {
    fetchSubscribers()
    fetchPlans()
  }, [fetchSubscribers, fetchPlans])

  const handleSuspend = async (sub) => {
    try {
      await axios.post(`/api/subscribers/${sub.id}/suspend`)
    } catch {
      // mock update
    }
    setSubscribers(prev => prev.map(s => s.id === sub.id ? { ...s, status: 'suspended' } : s))
    setConfirmSuspend(null)
  }

  const handleReactivate = async (sub) => {
    try {
      await axios.post(`/api/subscribers/${sub.id}/reactivate`)
    } catch {
      // mock update
    }
    setSubscribers(prev => prev.map(s => s.id === sub.id ? { ...s, status: 'active' } : s))
  }

  const handleResetPwd = async (sub) => {
    const pwd = prompt(`New password for ${sub.username}:`)
    if (!pwd) return
    try {
      await axios.post(`/api/subscribers/${sub.id}/reset-password`, { password: pwd })
      alert('Password reset successfully')
    } catch {
      alert('Password reset (mock - API unavailable)')
    }
  }

  const handleCreate = async (form) => {
    try {
      const res = await axios.post('/api/subscribers', form)
      setSubscribers(prev => [res.data, ...prev])
    } catch {
      // mock add
      const newSub = {
        id: Date.now(),
        username: form.username,
        name: form.name,
        phone: form.phone,
        plan: plans.find(p => p.id == form.plan_id)?.name || 'Unknown',
        status: 'pending',
        quota_gb: 50,
        used_gb: 0,
        expiry: new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10),
      }
      setSubscribers(prev => [newSub, ...prev])
    }
  }

  const filtered = subscribers.filter(s => {
    const matchStatus = statusFilter === 'All' || s.status.toLowerCase() === statusFilter.toLowerCase()
    const matchSearch = !search ||
      s.username?.toLowerCase().includes(search.toLowerCase()) ||
      s.name?.toLowerCase().includes(search.toLowerCase()) ||
      s.phone?.includes(search)
    return matchStatus && matchSearch
  })

  return (
    <div>
      <div className="page-header">
        <div className="page-title">Subscribers</div>
        <div className="flex items-center gap-2">
          {apiError && <span style={{ fontSize: 11, color: '#ffaa00' }}>Mock data</span>}
          <button className="btn" onClick={() => setShowModal(true)}>+ Add Subscriber</button>
        </div>
      </div>

      <div className="page-body">
        <div className="search-bar">
          <input
            type="search"
            placeholder="Search username, name, phone..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            style={{ width: 140 }}
          >
            {STATUS_FILTERS.map(s => <option key={s}>{s}</option>)}
          </select>
          <button className="btn btn-ghost btn-sm" onClick={fetchSubscribers}>Refresh</button>
        </div>

        <div style={{ fontSize: 11, color: '#555', marginBottom: 12 }}>
          Showing {filtered.length} of {subscribers.length}
        </div>

        {loading ? (
          <div className="text-muted" style={{ padding: 24 }}>Loading...</div>
        ) : (
          <div className="card">
            <div style={{ overflowX: 'auto' }}>
              <table>
                <thead>
                  <tr>
                    <th>Username</th>
                    <th>Name</th>
                    <th>Phone</th>
                    <th>Plan</th>
                    <th>Status</th>
                    <th>Quota</th>
                    <th>Expiry</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map(s => (
                    <tr key={s.id}>
                      <td className="text-accent">{s.username}</td>
                      <td>{s.name}</td>
                      <td className="text-muted">{s.phone}</td>
                      <td style={{ fontSize: 11 }}>{s.plan}</td>
                      <td><StatusBadge status={s.status} /></td>
                      <td style={{ minWidth: 120 }}>
                        <QuotaBar used={s.used_gb || 0} total={s.quota_gb} />
                      </td>
                      <td className="text-muted" style={{ fontSize: 11 }}>{s.expiry}</td>
                      <td>
                        <div className="flex gap-2">
                          {s.status === 'active' ? (
                            <button
                              className="btn btn-sm btn-warning"
                              onClick={() => setConfirmSuspend(s)}
                            >Suspend</button>
                          ) : (
                            <button
                              className="btn btn-sm"
                              onClick={() => handleReactivate(s)}
                            >Reactivate</button>
                          )}
                          <button
                            className="btn btn-sm btn-ghost"
                            onClick={() => handleResetPwd(s)}
                          >Reset PWD</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                  {filtered.length === 0 && (
                    <tr>
                      <td colSpan={8} style={{ textAlign: 'center', color: '#555', padding: 32 }}>
                        No subscribers found
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {showModal && (
        <AddModal
          plans={plans}
          onClose={() => setShowModal(false)}
          onSave={handleCreate}
        />
      )}

      {confirmSuspend && (
        <div className="modal-overlay" onClick={() => setConfirmSuspend(null)}>
          <div className="modal" style={{ width: 360 }} onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <span>Confirm Suspend</span>
              <button className="btn btn-ghost btn-sm" onClick={() => setConfirmSuspend(null)}>✕</button>
            </div>
            <div className="modal-body">
              <p style={{ fontSize: 13 }}>
                Suspend subscriber <span className="text-accent">{confirmSuspend.username}</span>?
                Their PPPoE session will be terminated immediately.
              </p>
            </div>
            <div className="modal-footer">
              <button className="btn btn-ghost" onClick={() => setConfirmSuspend(null)}>Cancel</button>
              <button className="btn btn-danger" onClick={() => handleSuspend(confirmSuspend)}>
                Suspend
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
