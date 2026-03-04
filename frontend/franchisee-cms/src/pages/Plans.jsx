import React, { useState, useEffect, useCallback } from 'react'
import axios from 'axios'

const OTT_OPTIONS = ['Chorki', 'Hoichoi', 'Binge', 'Toffee']

const MOCK_PLANS = [
  {
    id: 1, name: '10 Mbps Home', name_bn: '১০ এমবিপিএস হোম',
    download_kbps: 10240, upload_kbps: 5120, throttle_kbps: 512,
    data_cap_gb: 50, validity_days: 30, price: 600,
    ott: ['Chorki'], active_subscribers: 87, status: 'active'
  },
  {
    id: 2, name: '20 Mbps Home', name_bn: '২০ এমবিপিএস হোম',
    download_kbps: 20480, upload_kbps: 10240, throttle_kbps: 1024,
    data_cap_gb: 100, validity_days: 30, price: 900,
    ott: ['Chorki', 'Hoichoi'], active_subscribers: 143, status: 'active'
  },
  {
    id: 3, name: '50 Mbps Office', name_bn: '৫০ এমবিপিএস অফিস',
    download_kbps: 51200, upload_kbps: 25600, throttle_kbps: 2048,
    data_cap_gb: null, validity_days: 30, price: 1500,
    ott: [], active_subscribers: 34, status: 'active'
  },
  {
    id: 4, name: '100 Mbps Premium', name_bn: '১০০ এমবিপিএস প্রিমিয়াম',
    download_kbps: 102400, upload_kbps: 51200, throttle_kbps: null,
    data_cap_gb: null, validity_days: 30, price: 2500,
    ott: ['Chorki', 'Hoichoi', 'Binge', 'Toffee'], active_subscribers: 12, status: 'active'
  },
]

const EMPTY_FORM = {
  name: '', name_bn: '',
  download_kbps: '', upload_kbps: '', throttle_kbps: '',
  data_cap_gb: '', validity_days: 30, price: '',
  ott: [],
}

function PlanModal({ plan, onClose, onSave }) {
  const [form, setForm] = useState(plan ? {
    name: plan.name,
    name_bn: plan.name_bn || '',
    download_kbps: plan.download_kbps,
    upload_kbps: plan.upload_kbps,
    throttle_kbps: plan.throttle_kbps || '',
    data_cap_gb: plan.data_cap_gb || '',
    validity_days: plan.validity_days,
    price: plan.price,
    ott: plan.ott || [],
  } : { ...EMPTY_FORM, ott: [] })
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const toggleOtt = (item) => {
    setForm(f => ({
      ...f,
      ott: f.ott.includes(item) ? f.ott.filter(x => x !== item) : [...f.ott, item]
    }))
  }

  const handleSubmit = async e => {
    e.preventDefault()
    setSaving(true)
    setErr('')
    const payload = {
      ...form,
      download_kbps: Number(form.download_kbps),
      upload_kbps: Number(form.upload_kbps),
      throttle_kbps: form.throttle_kbps ? Number(form.throttle_kbps) : null,
      data_cap_gb: form.data_cap_gb ? Number(form.data_cap_gb) : null,
      validity_days: Number(form.validity_days),
      price: Number(form.price),
    }
    try {
      await onSave(payload)
      onClose()
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Failed to save plan')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span>{plan ? 'Edit Plan' : 'Create Plan'}</span>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>✕</button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            <div className="grid-2">
              <div className="form-group">
                <label>Plan Name (EN)</label>
                <input type="text" value={form.name} onChange={e => set('name', e.target.value)} required placeholder="10 Mbps Home" />
              </div>
              <div className="form-group">
                <label>Plan Name (BN)</label>
                <input type="text" value={form.name_bn} onChange={e => set('name_bn', e.target.value)} placeholder="১০ এমবিপিএস হোম" />
              </div>
            </div>
            <div className="grid-2">
              <div className="form-group">
                <label>Download (Kbps)</label>
                <input type="number" value={form.download_kbps} onChange={e => set('download_kbps', e.target.value)} required placeholder="10240" />
              </div>
              <div className="form-group">
                <label>Upload (Kbps)</label>
                <input type="number" value={form.upload_kbps} onChange={e => set('upload_kbps', e.target.value)} required placeholder="5120" />
              </div>
            </div>
            <div className="grid-2">
              <div className="form-group">
                <label>Throttle (Kbps, after cap)</label>
                <input type="number" value={form.throttle_kbps} onChange={e => set('throttle_kbps', e.target.value)} placeholder="512 (blank = disable)" />
              </div>
              <div className="form-group">
                <label>Data Cap (GB, blank = unlimited)</label>
                <input type="number" value={form.data_cap_gb} onChange={e => set('data_cap_gb', e.target.value)} placeholder="50" />
              </div>
            </div>
            <div className="grid-2">
              <div className="form-group">
                <label>Validity (Days)</label>
                <input type="number" value={form.validity_days} onChange={e => set('validity_days', e.target.value)} required placeholder="30" />
              </div>
              <div className="form-group">
                <label>Price (BDT)</label>
                <input type="number" value={form.price} onChange={e => set('price', e.target.value)} required placeholder="600" />
              </div>
            </div>
            <div className="form-group">
              <label>OTT Services</label>
              <div className="flex gap-2" style={{ flexWrap: 'wrap', marginTop: 8 }}>
                {OTT_OPTIONS.map(o => (
                  <label key={o} style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', textTransform: 'none', letterSpacing: 0 }}>
                    <input
                      type="checkbox"
                      checked={form.ott.includes(o)}
                      onChange={() => toggleOtt(o)}
                      style={{ width: 'auto', cursor: 'pointer' }}
                    />
                    <span style={{ fontSize: 12, color: '#e0e0e0' }}>{o}</span>
                  </label>
                ))}
              </div>
            </div>
            {err && <div style={{ color: '#ff4444', fontSize: 12 }}>{err}</div>}
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn" disabled={saving}>
              {saving ? 'Saving...' : plan ? 'Update Plan' : 'Create Plan'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function fmtSpeed(kbps) {
  if (!kbps) return 'N/A'
  return kbps >= 1024 ? `${(kbps / 1024).toFixed(0)} Mbps` : `${kbps} Kbps`
}

export default function Plans() {
  const [plans, setPlans] = useState(MOCK_PLANS)
  const [showModal, setShowModal] = useState(false)
  const [editPlan, setEditPlan] = useState(null)
  const [apiError, setApiError] = useState(false)
  const [loading, setLoading] = useState(false)

  const fetchPlans = useCallback(async () => {
    setLoading(true)
    try {
      const res = await axios.get('/api/plans')
      setPlans(res.data?.plans || res.data || MOCK_PLANS)
      setApiError(false)
    } catch {
      setApiError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchPlans() }, [fetchPlans])

  const handleCreate = async (form) => {
    try {
      const res = await axios.post('/api/plans', form)
      setPlans(prev => [...prev, res.data])
    } catch {
      setPlans(prev => [...prev, { ...form, id: Date.now(), active_subscribers: 0, status: 'active' }])
    }
  }

  const handleUpdate = async (form) => {
    try {
      const res = await axios.patch(`/api/plans/${editPlan.id}`, form)
      setPlans(prev => prev.map(p => p.id === editPlan.id ? res.data : p))
    } catch {
      setPlans(prev => prev.map(p => p.id === editPlan.id ? { ...p, ...form } : p))
    }
  }

  const handleDeactivate = async (plan) => {
    if (!confirm(`Deactivate plan "${plan.name}"?`)) return
    try {
      await axios.patch(`/api/plans/${plan.id}`, { status: 'inactive' })
    } catch {
      // mock
    }
    setPlans(prev => prev.map(p => p.id === plan.id ? { ...p, status: 'inactive' } : p))
  }

  return (
    <div>
      <div className="page-header">
        <div className="page-title">Plans</div>
        <div className="flex items-center gap-2">
          {apiError && <span style={{ fontSize: 11, color: '#ffaa00' }}>Mock data</span>}
          <button className="btn" onClick={() => { setEditPlan(null); setShowModal(true) }}>+ Create Plan</button>
        </div>
      </div>

      <div className="page-body">
        {loading ? (
          <div className="text-muted" style={{ padding: 24 }}>Loading...</div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 16 }}>
            {plans.map(plan => (
              <div key={plan.id} className="card" style={{ opacity: plan.status === 'inactive' ? 0.5 : 1 }}>
                <div className="card-header">
                  <span>{plan.name}</span>
                  {plan.status === 'inactive'
                    ? <span className="badge badge-terminated">Inactive</span>
                    : <span className="badge badge-active">Active</span>
                  }
                </div>
                {plan.name_bn && (
                  <div style={{ padding: '6px 16px', fontSize: 12, color: '#555', borderBottom: '1px solid #222' }}>
                    {plan.name_bn}
                  </div>
                )}
                <div className="card-body">
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 16px', marginBottom: 12 }}>
                    <div>
                      <div style={{ fontSize: 10, color: '#555', marginBottom: 2 }}>DOWNLOAD</div>
                      <div className="text-accent" style={{ fontSize: 15, fontWeight: 600 }}>{fmtSpeed(plan.download_kbps)}</div>
                    </div>
                    <div>
                      <div style={{ fontSize: 10, color: '#555', marginBottom: 2 }}>UPLOAD</div>
                      <div style={{ fontSize: 15, fontWeight: 600 }}>{fmtSpeed(plan.upload_kbps)}</div>
                    </div>
                    <div>
                      <div style={{ fontSize: 10, color: '#555', marginBottom: 2 }}>DATA CAP</div>
                      <div style={{ fontSize: 13 }}>{plan.data_cap_gb ? `${plan.data_cap_gb} GB` : 'Unlimited'}</div>
                    </div>
                    <div>
                      <div style={{ fontSize: 10, color: '#555', marginBottom: 2 }}>VALIDITY</div>
                      <div style={{ fontSize: 13 }}>{plan.validity_days}d</div>
                    </div>
                    {plan.throttle_kbps && (
                      <div>
                        <div style={{ fontSize: 10, color: '#555', marginBottom: 2 }}>THROTTLE</div>
                        <div style={{ fontSize: 13, color: '#ffaa00' }}>{fmtSpeed(plan.throttle_kbps)}</div>
                      </div>
                    )}
                    <div>
                      <div style={{ fontSize: 10, color: '#555', marginBottom: 2 }}>PRICE</div>
                      <div style={{ fontSize: 15, fontWeight: 600, color: '#00ff88' }}>৳{plan.price}</div>
                    </div>
                  </div>

                  {plan.ott?.length > 0 && (
                    <div style={{ marginBottom: 12 }}>
                      <div style={{ fontSize: 10, color: '#555', marginBottom: 6 }}>OTT</div>
                      <div className="flex gap-2" style={{ flexWrap: 'wrap' }}>
                        {plan.ott.map(o => (
                          <span key={o} className="badge badge-active" style={{ fontSize: 10 }}>{o}</span>
                        ))}
                      </div>
                    </div>
                  )}

                  <div style={{ fontSize: 11, color: '#555', marginBottom: 12 }}>
                    {plan.active_subscribers} active subscribers
                  </div>

                  <div className="flex gap-2">
                    <button
                      className="btn btn-sm btn-ghost"
                      onClick={() => { setEditPlan(plan); setShowModal(true) }}
                    >Edit</button>
                    {plan.status !== 'inactive' && (
                      <button
                        className="btn btn-sm btn-danger"
                        onClick={() => handleDeactivate(plan)}
                      >Deactivate</button>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {showModal && (
        <PlanModal
          plan={editPlan}
          onClose={() => { setShowModal(false); setEditPlan(null) }}
          onSave={editPlan ? handleUpdate : handleCreate}
        />
      )}
    </div>
  )
}
