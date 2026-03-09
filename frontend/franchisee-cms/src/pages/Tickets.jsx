import React, { useState, useEffect, useCallback } from 'react'
import axios from 'axios'

const MOCK_TICKETS = [
  {
    id: 1, subject: 'Internet down since morning', subscriber: 'client001',
    subscriber_name: 'Rahim Uddin', category: 'connectivity', priority: 'high',
    status: 'open', created: '2026-03-04 08:30',
    messages: [
      { id: 1, sender: 'client001', text: 'My internet has been down since 7am. Please fix ASAP.', time: '2026-03-04 08:30', is_staff: false },
    ]
  },
  {
    id: 2, subject: 'Speed lower than plan', subscriber: 'client003',
    subscriber_name: 'Nasrin Begum', category: 'speed', priority: 'medium',
    status: 'in_progress', created: '2026-03-04 07:15',
    messages: [
      { id: 1, sender: 'client003', text: 'I am getting only 5 Mbps but my plan is 50 Mbps.', time: '2026-03-04 07:15', is_staff: false },
      { id: 2, sender: 'Support', text: 'We are investigating. Please check your router.', time: '2026-03-04 07:45', is_staff: true },
    ]
  },
  {
    id: 3, subject: 'Unable to login', subscriber: 'client006',
    subscriber_name: 'Monir Hossain', category: 'account', priority: 'low',
    status: 'resolved', created: '2026-03-03 21:00',
    messages: [
      { id: 1, sender: 'client006', text: 'Cannot login with my username and password.', time: '2026-03-03 21:00', is_staff: false },
      { id: 2, sender: 'Support', text: 'Password has been reset. Please try the new password sent to your phone.', time: '2026-03-03 21:30', is_staff: true },
      { id: 3, sender: 'client006', text: 'Working now, thank you!', time: '2026-03-03 21:45', is_staff: false },
    ]
  },
  {
    id: 4, subject: 'Billing discrepancy', subscriber: 'client011',
    subscriber_name: 'Karim Hossain', category: 'billing', priority: 'medium',
    status: 'open', created: '2026-03-03 15:20',
    messages: [
      { id: 1, sender: 'client011', text: 'I was charged twice for this month.', time: '2026-03-03 15:20', is_staff: false },
    ]
  },
  {
    id: 5, subject: 'OTT service not working', subscriber: 'client019',
    subscriber_name: 'Farhana Islam', category: 'ott', priority: 'low',
    status: 'closed', created: '2026-03-02 11:00',
    messages: [
      { id: 1, sender: 'client019', text: 'Chorki is not loading on my plan.', time: '2026-03-02 11:00', is_staff: false },
      { id: 2, sender: 'Support', text: 'OTT service has been re-provisioned.', time: '2026-03-02 12:00', is_staff: true },
    ]
  },
  {
    id: 6, subject: 'Complete network outage', subscriber: 'client027',
    subscriber_name: 'Sabbir Ahmed', category: 'connectivity', priority: 'critical',
    status: 'in_progress', created: '2026-03-04 09:00',
    messages: [
      { id: 1, sender: 'client027', text: 'No internet at all. Multiple devices affected. Business impact!', time: '2026-03-04 09:00', is_staff: false },
      { id: 2, sender: 'Support', text: 'Escalated to network team. Technician dispatched.', time: '2026-03-04 09:15', is_staff: true },
    ]
  },
]

const PRIORITY_BADGE = {
  critical: { bg: 'rgba(255,68,68,0.1)', color: '#ff4444', border: 'rgba(255,68,68,0.3)' },
  high: { bg: 'rgba(255,170,0,0.1)', color: '#ffaa00', border: 'rgba(255,170,0,0.3)' },
  medium: { bg: 'rgba(0,136,255,0.1)', color: '#0088ff', border: 'rgba(0,136,255,0.3)' },
  low: { bg: 'rgba(100,100,100,0.15)', color: '#888888', border: '#444444' },
}

const STATUS_BADGE = {
  open: 'badge-pending',
  in_progress: 'badge-pending',
  resolved: 'badge-active',
  closed: 'badge-terminated',
}

function PriorityBadge({ priority }) {
  const s = PRIORITY_BADGE[priority] || PRIORITY_BADGE.low
  return (
    <span style={{
      display: 'inline-block', padding: '2px 8px', fontSize: 11,
      background: s.bg, color: s.color, border: `1px solid ${s.border}`
    }}>
      {priority}
    </span>
  )
}

function StatusBadge({ status }) {
  const cls = STATUS_BADGE[status] || 'badge-pending'
  const labels = { open: 'Open', in_progress: 'In Progress', resolved: 'Resolved', closed: 'Closed' }
  return <span className={`badge ${cls}`}>{labels[status] || status}</span>
}

function CreateTicketModal({ onClose, onSave }) {
  const [form, setForm] = useState({
    subject: '', subscriber: '', category: 'connectivity', priority: 'medium', message: ''
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
      setErr(ex.response?.data?.detail || 'Failed to create ticket')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <span>Create Ticket</span>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>✕</button>
        </div>
        <form onSubmit={handleSubmit}>
          <div className="modal-body">
            <div className="form-group">
              <label>Subject</label>
              <input type="text" value={form.subject} onChange={e => set('subject', e.target.value)} required placeholder="Brief description of the issue" />
            </div>
            <div className="form-group">
              <label>Subscriber Username</label>
              <input type="text" value={form.subscriber} onChange={e => set('subscriber', e.target.value)} required placeholder="client001" />
            </div>
            <div className="grid-2">
              <div className="form-group">
                <label>Category</label>
                <select value={form.category} onChange={e => set('category', e.target.value)}>
                  <option value="connectivity">Connectivity</option>
                  <option value="speed">Speed</option>
                  <option value="billing">Billing</option>
                  <option value="account">Account</option>
                  <option value="ott">OTT</option>
                  <option value="other">Other</option>
                </select>
              </div>
              <div className="form-group">
                <label>Priority</label>
                <select value={form.priority} onChange={e => set('priority', e.target.value)}>
                  <option value="critical">Critical</option>
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                </select>
              </div>
            </div>
            <div className="form-group">
              <label>Message</label>
              <textarea
                value={form.message}
                onChange={e => set('message', e.target.value)}
                rows={4}
                required
                placeholder="Describe the issue in detail..."
              />
            </div>
            {err && <div style={{ color: '#ff4444', fontSize: 12 }}>{err}</div>}
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-ghost" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn" disabled={saving}>
              {saving ? 'Creating...' : 'Create Ticket'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function TicketDetail({ ticket, onClose, onReply }) {
  const [replyText, setReplyText] = useState('')
  const [sending, setSending] = useState(false)
  const [messages, setMessages] = useState(ticket.messages || [])

  const handleReply = async e => {
    e.preventDefault()
    if (!replyText.trim()) return
    setSending(true)
    try {
      await onReply(ticket.id, replyText)
      setMessages(prev => [...prev, {
        id: Date.now(),
        sender: 'Support',
        text: replyText,
        time: new Date().toLocaleString('en-GB'),
        is_staff: true
      }])
      setReplyText('')
    } catch {
      // mock add
      setMessages(prev => [...prev, {
        id: Date.now(),
        sender: 'Support',
        text: replyText,
        time: new Date().toLocaleString('en-GB'),
        is_staff: true
      }])
      setReplyText('')
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" style={{ width: 620 }} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <div>
            <div style={{ fontSize: 14, marginBottom: 4 }}>{ticket.subject}</div>
            <div className="flex gap-2" style={{ gap: 8 }}>
              <PriorityBadge priority={ticket.priority} />
              <StatusBadge status={ticket.status} />
              <span className="text-muted" style={{ fontSize: 11 }}>#{ticket.id}</span>
            </div>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body" style={{ padding: '16px 20px' }}>
          <div style={{ marginBottom: 12, fontSize: 12, color: '#888' }}>
            Subscriber: <span className="text-accent">{ticket.subscriber}</span>
            {ticket.subscriber_name && ` (${ticket.subscriber_name})`}
            <span style={{ marginLeft: 12 }}>Category: {ticket.category}</span>
            <span style={{ marginLeft: 12 }}>Created: {ticket.created}</span>
          </div>

          {/* Message thread */}
          <div style={{ background: '#0a0a0a', border: '1px solid #1a1a1a', padding: 12, marginBottom: 16, maxHeight: 320, overflowY: 'auto' }}>
            {messages.map(msg => (
              <div
                key={msg.id}
                style={{
                  marginBottom: 12,
                  padding: '8px 12px',
                  background: msg.is_staff ? 'rgba(0,255,136,0.05)' : '#111',
                  border: `1px solid ${msg.is_staff ? 'rgba(0,255,136,0.15)' : '#1a1a1a'}`,
                }}
              >
                <div className="flex justify-between" style={{ marginBottom: 4 }}>
                  <span style={{ fontSize: 11, color: msg.is_staff ? '#00ff88' : '#888' }}>
                    {msg.sender}
                  </span>
                  <span style={{ fontSize: 10, color: '#555' }}>{msg.time}</span>
                </div>
                <div style={{ fontSize: 12 }}>{msg.text}</div>
              </div>
            ))}
            {messages.length === 0 && (
              <div className="text-muted" style={{ textAlign: 'center', padding: 16, fontSize: 12 }}>No messages</div>
            )}
          </div>

          {/* Reply form */}
          <form onSubmit={handleReply}>
            <div className="form-group">
              <label>Reply</label>
              <textarea
                value={replyText}
                onChange={e => setReplyText(e.target.value)}
                rows={3}
                placeholder="Type your reply..."
                required
              />
            </div>
            <div className="flex justify-between items-center">
              <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>Close</button>
              <button type="submit" className="btn btn-sm" disabled={sending || !replyText.trim()}>
                {sending ? 'Sending...' : 'Send Reply'}
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}

export default function Tickets() {
  const [tickets, setTickets] = useState(MOCK_TICKETS)
  const [showCreate, setShowCreate] = useState(false)
  const [selectedTicket, setSelectedTicket] = useState(null)
  const [apiError, setApiError] = useState(false)
  const [loading, setLoading] = useState(false)

  const fetchTickets = useCallback(async () => {
    setLoading(true)
    try {
      const res = await axios.get('/api/tickets')
      const data = res.data?.items ?? res.data?.tickets ?? res.data
      setTickets(Array.isArray(data) ? data : MOCK_TICKETS)
      setApiError(false)
    } catch {
      setApiError(true)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchTickets() }, [fetchTickets])

  const handleCreate = async (form) => {
    try {
      const res = await axios.post('/api/tickets', form)
      setTickets(prev => [res.data, ...prev])
    } catch {
      setTickets(prev => [{
        id: Date.now(),
        subject: form.subject,
        subscriber: form.subscriber,
        subscriber_name: '',
        category: form.category,
        priority: form.priority,
        status: 'open',
        created: new Date().toLocaleString('en-GB'),
        messages: [{ id: 1, sender: form.subscriber, text: form.message, time: new Date().toLocaleString('en-GB'), is_staff: false }]
      }, ...prev])
    }
  }

  const handleReply = async (ticketId, text) => {
    try {
      await axios.post(`/api/tickets/${ticketId}/reply`, { message: text })
    } catch {
      // mock — message already appended in TicketDetail
    }
  }

  const openCounts = tickets.filter(t => t.status === 'open').length
  const inProgressCounts = tickets.filter(t => t.status === 'in_progress').length

  return (
    <div>
      <div className="page-header">
        <div className="page-title">Support Tickets</div>
        <div className="flex items-center gap-2">
          {apiError && <span style={{ fontSize: 11, color: '#ffaa00' }}>Mock data</span>}
          <span className="badge badge-pending">{openCounts} open</span>
          <span className="badge badge-pending">{inProgressCounts} in progress</span>
          <button className="btn" onClick={() => setShowCreate(true)}>+ Create Ticket</button>
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
                    <th>#</th>
                    <th>Subject</th>
                    <th>Subscriber</th>
                    <th>Category</th>
                    <th>Priority</th>
                    <th>Status</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {tickets.map(t => (
                    <tr
                      key={t.id}
                      style={{ cursor: 'pointer' }}
                      onClick={() => setSelectedTicket(t)}
                    >
                      <td className="text-muted" style={{ fontSize: 11 }}>{t.id}</td>
                      <td>
                        <span style={{ fontSize: 12 }}>{t.subject}</span>
                        {t.messages?.length > 0 && (
                          <span className="text-muted" style={{ fontSize: 10, marginLeft: 8 }}>
                            {t.messages.length} msg{t.messages.length !== 1 ? 's' : ''}
                          </span>
                        )}
                      </td>
                      <td>
                        <div className="text-accent" style={{ fontSize: 12 }}>{t.subscriber}</div>
                        {t.subscriber_name && (
                          <div className="text-muted" style={{ fontSize: 10 }}>{t.subscriber_name}</div>
                        )}
                      </td>
                      <td style={{ fontSize: 11 }}>{t.category}</td>
                      <td><PriorityBadge priority={t.priority} /></td>
                      <td><StatusBadge status={t.status} /></td>
                      <td className="text-muted" style={{ fontSize: 11 }}>{t.created}</td>
                    </tr>
                  ))}
                  {tickets.length === 0 && (
                    <tr>
                      <td colSpan={7} style={{ textAlign: 'center', color: '#555', padding: 32 }}>
                        No tickets found
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {showCreate && (
        <CreateTicketModal
          onClose={() => setShowCreate(false)}
          onSave={handleCreate}
        />
      )}

      {selectedTicket && (
        <TicketDetail
          ticket={selectedTicket}
          onClose={() => setSelectedTicket(null)}
          onReply={handleReply}
        />
      )}
    </div>
  )
}
