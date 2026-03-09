import React, { useState, useEffect, useCallback } from 'react'
import axios from 'axios'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer
} from 'recharts'

const MOCK_OVERVIEW = {
  active_sessions: 142,
  download_today_gb: 318.7,
  monthly_revenue_bdt: 187500,
  subscribers_online: 142,
}

const MOCK_SESSIONS = [
  { username: 'client001', ip: '10.0.1.101', online_time: '3h 22m', down_mb: 2340, up_mb: 187 },
  { username: 'client002', ip: '10.0.1.102', online_time: '1h 05m', down_mb: 890, up_mb: 54 },
  { username: 'client003', ip: '10.0.1.103', online_time: '7h 48m', down_mb: 5120, up_mb: 430 },
  { username: 'client004', ip: '10.0.1.104', online_time: '0h 33m', down_mb: 210, up_mb: 18 },
  { username: 'client005', ip: '10.0.1.105', online_time: '2h 14m', down_mb: 1650, up_mb: 99 },
]

const MOCK_TOP_CONSUMERS = [
  { name: 'Rahim Uddin', username: 'client003', usage_gb: 48.2 },
  { name: 'Karim Hossain', username: 'client011', usage_gb: 39.7 },
  { name: 'Nasrin Begum', username: 'client027', usage_gb: 31.4 },
  { name: 'Sabbir Ahmed', username: 'client008', usage_gb: 28.1 },
  { name: 'Farhana Islam', username: 'client019', usage_gb: 22.6 },
]

function generateMockChart() {
  return Array.from({ length: 24 }, (_, i) => ({
    hour: `${String(i).padStart(2, '0')}:00`,
    download: Math.round(Math.random() * 800 + 100),
    upload: Math.round(Math.random() * 200 + 20),
  }))
}

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null
  return (
    <div style={{ background: '#1a1a1a', border: '1px solid #222', padding: '8px 12px', fontSize: 11 }}>
      <div style={{ color: '#888', marginBottom: 4 }}>{label}</div>
      {payload.map(p => (
        <div key={p.name} style={{ color: p.color }}>
          {p.name}: {p.value} Mbps
        </div>
      ))}
    </div>
  )
}

export default function Dashboard() {
  const [overview, setOverview] = useState(MOCK_OVERVIEW)
  const [sessions, setSessions] = useState(MOCK_SESSIONS)
  const [topConsumers, setTopConsumers] = useState(MOCK_TOP_CONSUMERS)
  const [chartData, setChartData] = useState(generateMockChart)
  const [lastUpdated, setLastUpdated] = useState(new Date())
  const [apiError, setApiError] = useState(false)

  const fetchData = useCallback(async () => {
    try {
      const [ovRes, sessRes] = await Promise.all([
        axios.get('/api/usage/franchisee/overview'),
        axios.get('/api/usage/franchisee/sessions'),
      ])
      setOverview(ovRes.data)
      const sessData = sessRes.data?.sessions ?? sessRes.data
      setSessions(Array.isArray(sessData) ? sessData : MOCK_SESSIONS)
      setApiError(false)
    } catch {
      setApiError(true)
      // keep mock data
    }

    try {
      const topRes = await axios.get('/api/usage/franchisee/top-consumers')
      const topData = topRes.data?.consumers ?? topRes.data
      setTopConsumers(Array.isArray(topData) ? topData : MOCK_TOP_CONSUMERS)
    } catch {
      // keep mock
    }

    try {
      const chartRes = await axios.get('/api/usage/franchisee/chart?range=24h')
      if (chartRes.data?.length) setChartData(chartRes.data)
    } catch {
      // keep mock
    }

    setLastUpdated(new Date())
  }, [])

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 30000)
    return () => clearInterval(interval)
  }, [fetchData])

  const maxConsumer = topConsumers[0]?.usage_gb || 1

  const fmtMb = mb => mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb} MB`

  return (
    <div>
      <div className="page-header">
        <div className="page-title">
          <span className="live-dot" />
          Dashboard
        </div>
        <div className="flex items-center gap-2">
          {apiError && (
            <span style={{ fontSize: 11, color: '#ffaa00' }}>API unavailable — showing mock data</span>
          )}
          <span className="text-muted" style={{ fontSize: 11 }}>
            Updated {lastUpdated.toLocaleTimeString()}
          </span>
          <button className="btn btn-sm btn-ghost" onClick={fetchData}>Refresh</button>
        </div>
      </div>

      <div className="page-body">
        {/* Stat Cards */}
        <div className="stat-grid">
          <div className="stat-card">
            <div className="stat-label">Active Sessions</div>
            <div className="stat-value">{overview.active_sessions}</div>
            <div className="stat-sub">PPPoE connections live</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Today's Download</div>
            <div className="stat-value">{overview.download_today_gb?.toFixed(1)}</div>
            <div className="stat-sub">GB transferred today</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Monthly Revenue</div>
            <div className="stat-value">{(overview.monthly_revenue_bdt / 1000).toFixed(1)}k</div>
            <div className="stat-sub">BDT this month</div>
          </div>
          <div className="stat-card">
            <div className="stat-label">Subscribers Online</div>
            <div className="stat-value">{overview.subscribers_online}</div>
            <div className="stat-sub">currently active</div>
          </div>
        </div>

        {/* 24h Traffic Chart */}
        <div className="card mb-6">
          <div className="card-header">
            <span>24-Hour Traffic</span>
            <span className="text-muted" style={{ fontSize: 11 }}>Mbps</span>
          </div>
          <div className="card-body" style={{ paddingTop: 8 }}>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1a1a1a" vertical={false} />
                <XAxis
                  dataKey="hour"
                  tick={{ fill: '#555', fontSize: 10 }}
                  tickLine={false}
                  axisLine={{ stroke: '#222' }}
                  interval={3}
                />
                <YAxis
                  tick={{ fill: '#555', fontSize: 10 }}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(0,255,136,0.05)' }} />
                <Bar dataKey="download" name="Download" fill="#00ff88" opacity={0.8} radius={[1, 1, 0, 0]} />
                <Bar dataKey="upload" name="Upload" fill="#0088ff" opacity={0.7} radius={[1, 1, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="grid-2">
          {/* Top Consumers */}
          <div className="card">
            <div className="card-header">Top 5 Consumers</div>
            <div className="card-body" style={{ padding: 0 }}>
              {topConsumers.slice(0, 5).map((c, i) => (
                <div key={c.username} style={{ padding: '10px 16px', borderBottom: '1px solid #222' }}>
                  <div className="flex justify-between items-center" style={{ marginBottom: 4 }}>
                    <span style={{ fontSize: 12 }}>
                      <span className="text-muted" style={{ marginRight: 8 }}>#{i + 1}</span>
                      {c.name || c.username}
                    </span>
                    <span className="text-accent" style={{ fontSize: 12 }}>{c.usage_gb.toFixed(1)} GB</span>
                  </div>
                  <div className="progress">
                    <div
                      className="progress-bar"
                      style={{ width: `${Math.min(100, (c.usage_gb / maxConsumer) * 100)}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Active Sessions */}
          <div className="card">
            <div className="card-header">
              <span>Active PPPoE Sessions</span>
              <span className="badge badge-active">{sessions.length}</span>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table>
                <thead>
                  <tr>
                    <th>Username</th>
                    <th>IP</th>
                    <th>Time</th>
                    <th>Down</th>
                    <th>Up</th>
                  </tr>
                </thead>
                <tbody>
                  {sessions.slice(0, 8).map(s => (
                    <tr key={s.username}>
                      <td className="text-accent">{s.username}</td>
                      <td className="text-muted">{s.ip}</td>
                      <td>{s.online_time}</td>
                      <td className="text-accent">{fmtMb(s.down_mb)}</td>
                      <td className="text-muted">{fmtMb(s.up_mb)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
