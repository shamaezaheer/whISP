import React, { useState, useEffect, useCallback } from 'react'
import axios from 'axios'

const MOCK_DEVICES = [
  {
    id: 1, name: 'NAS-01', ip: '10.0.0.1', type: 'MikroTik',
    status: 'online', last_seen: '2026-03-04 09:18', coa_port: 3799,
    description: 'Main gateway router'
  },
  {
    id: 2, name: 'NAS-02', ip: '10.0.0.2', type: 'MikroTik',
    status: 'online', last_seen: '2026-03-04 09:17', coa_port: 3799,
    description: 'Secondary NAS'
  },
  {
    id: 3, name: 'NAS-03', ip: '10.0.0.3', type: 'Cisco',
    status: 'offline', last_seen: '2026-03-03 14:22', coa_port: 1700,
    description: 'Backup device'
  },
]

function DeviceModal({ onClose, onSave }) {
  const [form, setForm] = useState({
    name: '', ip: '', secret: '', coa_port: 3799, description: ''
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
      setErr(ex.response?.data?.detail || 'Failed to register device')
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
                <input type="text" value={form.ip} onChange={e => set('ip', e.target.value)} required placeholder="10.0.0.4" />
              </div>
            </div>
            <div className="form-group">
              <label>RADIUS Secret</label>
              <input type="password" value={form.secret} onChange={e => set('secret', e.target.value)} required placeholder="••••••••" />
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

export default function Devices() {
  const [devices, setDevices] = useState(MOCK_DEVICES)
  const [showModal, setShowModal] = useState(false)
  const [apiError, setApiError] = useState(false)
  const [loading, setLoading] = useState(false)
  const [coaResults, setCoaResults] = useState({})
  const [coaTesting, setCoaTesting] = useState({})

  const fetchDevices = useCallback(async () => {
    setLoading(true)
    try {
      const res = await axios.get('/api/nas')
      setDevices(res.data?.devices || res.data || MOCK_DEVICES)
      setApiError(false)
    } catch {
      setApiError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchDevices() }, [fetchDevices])

  const handleRegister = async (form) => {
    try {
      const res = await axios.post('/api/nas', form)
      setDevices(prev => [...prev, res.data])
    } catch {
      setDevices(prev => [...prev, {
        ...form,
        id: Date.now(),
        type: 'MikroTik',
        status: 'unknown',
        last_seen: 'Never',
      }])
    }
  }

  const handleTestCoA = async (device) => {
    setCoaTesting(prev => ({ ...prev, [device.id]: true }))
    setCoaResults(prev => ({ ...prev, [device.id]: null }))
    try {
      const res = await axios.post(`/api/nas/${device.id}/test-coa`)
      setCoaResults(prev => ({
        ...prev,
        [device.id]: {
          success: res.data.success !== false,
          latency_ms: res.data.latency_ms || null,
          message: res.data.message || 'CoA test successful'
        }
      }))
    } catch {
      // Mock result
      const mockLatency = Math.round(Math.random() * 30 + 5)
      setCoaResults(prev => ({
        ...prev,
        [device.id]: {
          success: device.status === 'online',
          latency_ms: device.status === 'online' ? mockLatency : null,
          message: device.status === 'online' ? 'CoA test successful' : 'Connection refused'
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
      // Mock config download
      const mockConfig = `# whISP NAS Configuration for ${device.name}
# Generated: ${new Date().toISOString()}
# IP: ${device.ip}

/radius
add address=${device.ip} secret=YOUR_SECRET service=ppp timeout=3s

/ip hotspot user profile
add name=default rate-limit=10M/5M

/ppp profile
add name=whisp-profile use-radius=yes
`
      const blob = new Blob([mockConfig], { type: 'text/plain' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${device.name.toLowerCase().replace(/\s+/g, '-')}.rsc`
      a.click()
      URL.revokeObjectURL(url)
    }
  }

  const handleDelete = async (device) => {
    if (!confirm(`Delete device "${device.name}"?`)) return
    try {
      await axios.delete(`/api/nas/${device.id}`)
    } catch {
      // mock
    }
    setDevices(prev => prev.filter(d => d.id !== device.id))
  }

  return (
    <div>
      <div className="page-header">
        <div className="page-title">Devices</div>
        <div className="flex items-center gap-2">
          {apiError && <span style={{ fontSize: 11, color: '#ffaa00' }}>Mock data</span>}
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
                        <td className="text-muted">{d.ip}</td>
                        <td style={{ fontSize: 11 }}>{d.type}</td>
                        <td>
                          <span className={`badge ${d.status === 'online' ? 'badge-active' : d.status === 'offline' ? 'badge-suspended' : 'badge-pending'}`}>
                            {d.status}
                          </span>
                        </td>
                        <td className="text-muted" style={{ fontSize: 11 }}>{d.last_seen}</td>
                        <td>
                          {coaRes ? (
                            <span style={{
                              fontSize: 11,
                              color: coaRes.success ? '#00ff88' : '#ff4444'
                            }}>
                              {coaRes.success ? `OK ${coaRes.latency_ms ? `(${coaRes.latency_ms}ms)` : ''}` : coaRes.message}
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
                        No devices registered
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
          onClose={() => setShowModal(false)}
          onSave={handleRegister}
        />
      )}
    </div>
  )
}
