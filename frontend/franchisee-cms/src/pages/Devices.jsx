import React, { useState, useEffect, useCallback } from 'react'
import axios from 'axios'
import { useAuth } from '../hooks/useAuth'

function DeviceModal({ franchiseeId, onClose, onSave }) {
  const [form, setForm] = useState({
    name: '', ip_address: '', secret: '', coa_port: 3799, description: ''
  })
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  const handleSubmit = async e => {
    e.preventDefault()
    setSaving(true)
    setErr('')
    try {
      await onSave({ ...form, franchisee_id: franchiseeId })
      onClose()
    } catch (ex) {
      const detail = ex.response?.data?.detail
      setErr(Array.isArray(detail)
        ? detail.map(d => d.msg).join(', ')
        : detail || 'Failed to register device')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span>Register Device</span>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>✕</button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            <div className="grid-2">
              <div className="form-group">
                <label>Device Name</label>
                <input type="text" value={form.name} onChange={e => set('name', e.target.value)} required placeholder="NAS-04" />
              </div>
              <div className="form-group">
                <label>IP Address</label>
                <input type="text" value={form.ip_address} onChange={e => set('ip_address', e.target.value)} required placeholder="10.0.0.4" />
              </div>
            </div>
            <div className="form-group">
              <label>RADIUS Secret <span style={{ color: '#555', fontWeight: 400 }}>(leave blank to inherit franchisee secret)</span></label>
              <input type="password" value={form.secret} onChange={e => set('secret', e.target.value)} placeholder="Leave blank to auto-assign" />
            </div>
            <div className="form-group">
              <label>CoA Port</label>
              <input type="number" value={form.coa_port} onChange={e => set('coa_port', Number(e.target.value))} placeholder="3799" />
            </div>
            <div className="form-group">
              <label>Description</label>
              <textarea
                value={form.description}
                onChange={e => set('description', e.target.value)}
                rows={2}
                placeholder="Optional description..."
              />
            </div>
            {err && <div style={{ color: '#ff4444', fontSize: 12 }}>{err}</div>}
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn" disabled={saving}>
              {saving ? 'Registering...' : 'Register Device'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function deviceStatus(d) {
  if (!d.is_active) return 'inactive'
  if (!d.last_seen_at) return 'unknown'
  const diffMin = (Date.now() - new Date(d.last_seen_at).getTime()) / 60000
  return diffMin < 10 ? 'online' : 'offline'
}

export default function Devices() {
  const { user } = useAuth()
  const [devices, setDevices] = useState([])
  const [showModal, setShowModal] = useState(false)
  const [apiError, setApiError] = useState(false)
  const [loading, setLoading] = useState(false)
  const [coaResults, setCoaResults] = useState({})
  const [coaTesting, setCoaTesting] = useState({})

  const fetchDevices = useCallback(async () => {
    setLoading(true)
    try {
      const res = await axios.get('/api/nas')
      const data = res.data?.items ?? res.data?.devices ?? res.data
      setDevices(Array.isArray(data) ? data : [])
      setApiError(false)
    } catch {
      setApiError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchDevices() }, [fetchDevices])

  const handleRegister = async (form) => {
    // Strip blank secret so API inherits from franchisee
    const payload = { ...form }
    if (!payload.secret) delete payload.secret
    const res = await axios.post('/api/nas', payload)
    setDevices(prev => [...prev, res.data])
  }

  const handleTestCoA = async (device) => {
    setCoaTesting(prev => ({ ...prev, [device.id]: true }))
    setCoaResults(prev => ({ ...prev, [device.id]: null }))
    try {
      const res = await axios.post(`/api/nas/${device.id}/test-coa`)
      setCoaResults(prev => ({
        ...prev,
        [device.id]: {
          success: res.data.success,
          latency_ms: res.data.latency_ms,
          message: res.data.message,
        }
      }))
    } catch (ex) {
      setCoaResults(prev => ({
        ...prev,
        [device.id]: {
          success: false,
          latency_ms: null,
          message: ex.response?.data?.detail || 'CoA test failed',
        }
      }))
    } finally {
      setCoaTesting(prev => ({ ...prev, [device.id]: false }))
    }
  }

  const handleDownloadConfig = async (device) => {
    try {
      const res = await axios.get(`/api/nas/${device.id}/config`, { responseType: 'text' })
      const blob = new Blob([res.data], { type: 'text/plain' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${device.name.toLowerCase().replace(/\s+/g, '-')}.rsc`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      alert('Failed to download config — API unavailable')
    }
  }

  const handleDelete = async (device) => {
    if (!confirm(`Delete device "${device.name}"?`)) return
    try {
      await axios.delete(`/api/nas/${device.id}`)
      setDevices(prev => prev.filter(d => d.id !== device.id))
    } catch (ex) {
      alert(ex.response?.data?.detail || 'Failed to delete device')
    }
  }

  return (
    <div>
      <div className="page-header">
        <div className="page-title">Devices</div>
        <div className="flex items-center gap-2">
          {apiError && <span style={{ fontSize: 11, color: '#ffaa00' }}>API unavailable</span>}
          <button className="btn" onClick={() => setShowModal(true)}>+ Register Device</button>
        </div>
      </div>

      <div className="page-body">
        {loading ? (
          <div className="text-muted" style={{ padding: 24 }}>Loading...</div>
        ) : (
          <div className="card">
            <div style={{ overflowX: 'auto' }}>
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>IP Address</th>
                    <th>Type</th>
                    <th>Status</th>
                    <th>Last Seen</th>
                    <th>CoA Test</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {devices.map(d => {
                    const status = deviceStatus(d)
                    const coaRes = coaResults[d.id]
                    const testing = coaTesting[d.id]
                    return (
                      <tr key={d.id}>
                        <td>
                          <div className="text-accent">{d.name}</div>
                          {d.description && (
                            <div className="text-muted" style={{ fontSize: 10 }}>{d.description}</div>
                          )}
                        </td>
                        <td className="text-muted">{d.ip_address}</td>
                        <td style={{ fontSize: 11 }}>{d.nas_type}</td>
                        <td>
                          <span className={`badge ${status === 'online' ? 'badge-active' : status === 'offline' ? 'badge-suspended' : 'badge-pending'}`}>
                            {status}
                          </span>
                        </td>
                        <td className="text-muted" style={{ fontSize: 11 }}>
                          {d.last_seen_at ? new Date(d.last_seen_at).toLocaleString() : 'Never'}
                        </td>
                        <td>
                          {coaRes ? (
                            <span style={{ fontSize: 11, color: coaRes.success ? '#00ff88' : '#ff4444' }}>
                              {coaRes.success
                                ? `OK${coaRes.latency_ms ? ` (${coaRes.latency_ms}ms)` : ''}`
                                : coaRes.message}
                            </span>
                          ) : (
                            <span className="text-muted" style={{ fontSize: 11 }}>—</span>
                          )}
                        </td>
                        <td>
                          <div className="flex gap-2">
                            <button
                              className="btn btn-sm btn-ghost"
                              onClick={() => handleTestCoA(d)}
                              disabled={testing}
                            >
                              {testing ? 'Testing...' : 'Test CoA'}
                            </button>
                            <button
                              className="btn btn-sm btn-ghost"
                              onClick={() => handleDownloadConfig(d)}
                            >
                              Config
                            </button>
                            <button
                              className="btn btn-sm btn-danger"
                              onClick={() => handleDelete(d)}
                            >
                              Delete
                            </button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                  {devices.length === 0 && (
                    <tr>
                      <td colSpan={7} style={{ textAlign: 'center', color: '#555', padding: 32 }}>
                        {apiError ? 'Could not load devices — check API connection' : 'No devices registered'}
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
        <DeviceModal
          franchiseeId={user?.franchisee_id}
          onClose={() => setShowModal(false)}
          onSave={handleRegister}
        />
      )}
    </div>
  )
}
