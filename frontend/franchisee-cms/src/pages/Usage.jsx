import React, { useState, useEffect, useCallback } from 'react'
import axios from 'axios'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from 'recharts'

const RANGES = ['6h', '24h', '72h', '7d']

function generateMockChart(range) {
  const points = { '6h': 72, '24h': 96, '72h': 72, '7d': 168 }[range] || 96
  return Array.from({ length: points }, (_, i) => {
    const now = Date.now()
    const step = { '6h': 5 * 60000, '24h': 15 * 60000, '72h': 60 * 60000, '7d': 60 * 60000 }[range] || 15 * 60000
    const ts = new Date(now - (points - i) * step)
    const label = range === '7d'
      ? ts.toLocaleDateString('en-GB', { month: 'short', day: 'numeric', hour: '2-digit' })
      : ts.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
    return {
      time: label,
      bytes_in: Math.round((Math.random() * 600 + 100) * 1e6),
      bytes_out: Math.round((Math.random() * 150 + 20) * 1e6),
    }
  })
}

const MOCK_TOP = [
  { rank: 1, username: 'client003', plan: '50 Mbps Office', usage_gb: 48.2 },
  { rank: 2, username: 'client011', plan: '20 Mbps Home', usage_gb: 39.7 },
  { rank: 3, username: 'client027', plan: '100 Mbps Premium', usage_gb: 31.4 },
  { rank: 4, username: 'client008', plan: '10 Mbps Home', usage_gb: 28.1 },
  { rank: 5, username: 'client019', plan: '20 Mbps Home', usage_gb: 22.6 },
  { rank: 6, username: 'client034', plan: '50 Mbps Office', usage_gb: 19.3 },
  { rank: 7, username: 'client002', plan: '10 Mbps Home', usage_gb: 15.8 },
  { rank: 8, username: 'client047', plan: '20 Mbps Home', usage_gb: 12.4 },
  { rank: 9, username: 'client015', plan: '100 Mbps Premium', usage_gb: 10.2 },
  { rank: 10, username: 'client062', plan: '10 Mbps Home', usage_gb: 8.7 },
]

const MOCK_SESSIONS = [
  { username: 'client001', ip: '10.0.1.101', nas: 'NAS-01', online_since: '2026-03-04 06:32' },
  { username: 'client003', ip: '10.0.1.103', nas: 'NAS-01', online_since: '2026-03-04 00:15' },
  { username: 'client006', ip: '10.0.1.106', nas: 'NAS-02', online_since: '2026-03-04 08:47' },
  { username: 'client011', ip: '10.0.1.111', nas: 'NAS-02', online_since: '2026-03-04 07:11' },
  { username: 'client019', ip: '10.0.1.119', nas: 'NAS-01', online_since: '2026-03-04 09:02' },
]

function fmtBytes(b) {
  if (b >= 1e9) return `${(b / 1e9).toFixed(1)} GB`
  if (b >= 1e6) return `${(b / 1e6).toFixed(0)} MB`
  return `${b} B`
}

const ChartTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div style={{ background: '#1a1a1a', border: '1px solid #222', padding: '8px 12px', fontSize: 11 }}>
      <div style={{ color: '#888', marginBottom: 4 }}>{label}</div>
      {payload.map(p => (
        <div key={p.name} style={{ color: p.color }}>
          {p.name}: {fmtBytes(p.value)}
        </div>
      ))}
    </div>
  )
}

export default function Usage() {
  const [range, setRange] = useState('24h')
  const [chartData, setChartData] = useState(() => generateMockChart('24h'))
  const [topConsumers, setTopConsumers] = useState(MOCK_TOP)
  const [sessions, setSessions] = useState(MOCK_SESSIONS)
  const [loading, setLoading] = useState(false)
  const [apiError, setApiError] = useState(false)

  const fetchChart = useCallback(async (r) => {
    setLoading(true)
    try {
      const res = await axios.get(`/api/usage/franchisee/chart?range=${r}`)
      if (res.data?.length) setChartData(res.data)
      else setChartData(generateMockChart(r))
      setApiError(false)
    } catch {
      setChartData(generateMockChart(r))
      setApiError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  const fetchTop = useCallback(async () => {
    try {
      const res = await axios.get('/api/usage/franchisee/top-consumers')
      const topData = res.data?.consumers ?? res.data
      setTopConsumers(Array.isArray(topData) ? topData : MOCK_TOP)
    } catch {
      // keep mock
    }
  }, [])

  const fetchSessions = useCallback(async () => {
    try {
      const res = await axios.get('/api/usage/franchisee/sessions')
      const sessData = res.data?.sessions ?? res.data
      setSessions(Array.isArray(sessData) ? sessData : MOCK_SESSIONS)
    } catch {
      // keep mock
    }
  }, [])

  useEffect(() => {
    fetchChart(range)
    fetchTop()
    fetchSessions()
  }, [range, fetchChart, fetchTop, fetchSessions])

  const maxUsage = topConsumers[0]?.usage_gb || 1

  const tickFormatter = (v) => {
    if (v >= 1e9) return `${(v / 1e9).toFixed(0)}G`
    if (v >= 1e6) return `${(v / 1e6).toFixed(0)}M`
    return v
  }

  return (
    <div>
      <div className="page-header">
        <div className="page-title">Usage Analytics</div>
        <div className="flex items-center gap-2">
          {apiError && <span style={{ fontSize: 11, color: '#ffaa00' }}>Mock data</span>}
          <span className="live-dot" />
          <span style={{ fontSize: 11, color: '#555' }}>{sessions.length} live sessions</span>
        </div>
      </div>

      <div className="page-body">
        {/* Range selector */}
        <div className="flex gap-2 mb-4">
          {RANGES.map(r => (
            <button
              key={r}
              className={`btn btn-sm ${range === r ? '' : 'btn-ghost'}`}
              onClick={() => setRange(r)}
            >
              {r}
            </button>
          ))}
        </div>

        {/* Traffic chart */}
        <div className="card mb-6">
          <div className="card-header">
            <span>Traffic Volume</span>
            <span className="text-muted" style={{ fontSize: 11 }}>bytes_in + bytes_out</span>
          </div>
          <div className="card-body" style={{ paddingTop: 8 }}>
            {loading ? (
              <div className="text-muted" style={{ textAlign: 'center', padding: 40 }}>Loading chart...</div>
            ) : (
              <ResponsiveContainer width="100%" height={240}>
                <AreaChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                  <defs>
                    <linearGradient id="colorIn" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#00ff88" stopOpacity={0.25} />
                      <stop offset="95%" stopColor="#00ff88" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="colorOut" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#0088ff" stopOpacity={0.2} />
                      <stop offset="95%" stopColor="#0088ff" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" vertical={false} />
                  <XAxis
                    dataKey="time"
                    tick={{ fill: '#555', fontSize: 10 }}
                    tickLine={false}
                    axisLine={{ stroke: '#222' }}
                    interval={Math.floor(chartData.length / 8)}
                  />
                  <YAxis
                    tickFormatter={tickFormatter}
                    tick={{ fill: '#555', fontSize: 10 }}
                    tickLine={false}
                    axisLine={false}
                    width={40}
                  />
                  <Tooltip content={<ChartTooltip />} />
                  <Area
                    type="monotone"
                    dataKey="bytes_in"
                    name="Download"
                    stroke="#00ff88"
                    strokeWidth={1.5}
                    fill="url(#colorIn)"
                    dot={false}
                  />
                  <Area
                    type="monotone"
                    dataKey="bytes_out"
                    name="Upload"
                    stroke="#0088ff"
                    strokeWidth={1.5}
                    fill="url(#colorOut)"
                    dot={false}
                  />
                </AreaChart>
              </ResponsiveContainer>
            )}
          </div>
        </div>

        <div className="grid-2">
          {/* Top Consumers */}
          <div className="card">
            <div className="card-header">Top Consumers</div>
            <div style={{ padding: '8px 0' }}>
              {topConsumers.map(c => (
                <div key={c.username} style={{ padding: '8px 16px', borderBottom: '1px solid #1a1a1a' }}>
                  <div className="flex justify-between items-center" style={{ marginBottom: 4 }}>
                    <div>
                      <span className="text-muted" style={{ fontSize: 10, marginRight: 8 }}>#{c.rank}</span>
                      <span className="text-accent" style={{ fontSize: 12 }}>{c.username}</span>
                      <span className="text-muted" style={{ fontSize: 10, marginLeft: 8 }}>{c.plan}</span>
                    </div>
                    <span style={{ fontSize: 12, fontWeight: 600 }}>{c.usage_gb.toFixed(1)} GB</span>
                  </div>
                  <div className="progress">
                    <div
                      className="progress-bar"
                      style={{ width: `${Math.min(100, (c.usage_gb / maxUsage) * 100)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Live Sessions */}
          <div className="card">
            <div className="card-header">
              <span>Live Sessions</span>
              <span className="badge badge-active">{sessions.length}</span>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table>
                <thead>
                  <tr>
                    <th>Username</th>
                    <th>IP Address</th>
                    <th>NAS</th>
                    <th>Online Since</th>
                  </tr>
                </thead>
                <tbody>
                  {sessions.map(s => (
                    <tr key={s.username}>
                      <td className="text-accent">{s.username}</td>
                      <td className="text-muted">{s.ip}</td>
                      <td style={{ fontSize: 11 }}>{s.nas}</td>
                      <td className="text-muted" style={{ fontSize: 11 }}>{s.online_since}</td>
                    </tr>
                  ))}
                  {sessions.length === 0 && (
                    <tr>
                      <td colSpan={4} style={{ textAlign: 'center', color: '#555', padding: 24 }}>No active sessions</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
