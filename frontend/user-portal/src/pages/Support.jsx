import React, { useState, useEffect } from 'react'

const CATEGORIES = [
  { id: 'connection', label: 'সংযোগ সমস্যা', emoji: '🔌' },
  { id: 'billing', label: 'বিল সংক্রান্ত', emoji: '💳' },
  { id: 'speed', label: 'গতি কম', emoji: '🐢' },
  { id: 'other', label: 'অন্যান্য', emoji: '📋' },
]

const MOCK_TICKETS = [
  {
    id: 't1',
    subject: 'সংযোগ বিচ্ছিন্ন হচ্ছে',
    category: 'connection',
    status: 'open',
    created_at: '2026-03-02T10:00:00Z',
    messages: [
      { sender: 'subscriber', body: 'আমার ইন্টারনেট বারবার বিচ্ছিন্ন হচ্ছে।', created_at: '2026-03-02T10:00:00Z' },
      { sender: 'agent', body: 'আমরা আপনার সমস্যাটি দেখছি। ১-২ ঘণ্টার মধ্যে সমাধান হবে।', created_at: '2026-03-02T11:30:00Z' },
    ],
  },
  {
    id: 't2',
    subject: 'গতি খুব কম',
    category: 'speed',
    status: 'resolved',
    created_at: '2026-02-20T14:00:00Z',
    messages: [
      { sender: 'subscriber', body: 'আমার ইন্টারনেট গতি প্যাকেজের তুলনায় অনেক কম।', created_at: '2026-02-20T14:00:00Z' },
      { sender: 'agent', body: 'সমস্যাটি সমাধান করা হয়েছে।', created_at: '2026-02-21T09:00:00Z' },
    ],
  },
]

function StatusBadge({ status }) {
  if (status === 'open') return <span className="badge badge-suspended">খোলা</span>
  if (status === 'resolved') return <span className="badge badge-active">সমাধান</span>
  if (status === 'closed') return <span className="badge" style={{ background: '#f4f6f8', color: '#6b7280' }}>বন্ধ</span>
  return <span className="badge badge-expired">অজানা</span>
}

function formatDate(dateStr) {
  const d = new Date(dateStr)
  return d.toLocaleDateString('bn-BD', { day: '2-digit', month: 'short', year: 'numeric' })
}

function TicketThread({ ticket, onBack }) {
  const [reply, setReply] = useState('')
  const [sending, setSending] = useState(false)
  const [messages, setMessages] = useState(ticket.messages || [])

  const handleSend = async () => {
    if (!reply.trim()) return
    const token = localStorage.getItem('whisp_sub_token')
    setSending(true)
    try {
      const res = await fetch(`/api/tickets/${ticket.id}/messages`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ body: reply }),
      })
      if (res.ok) {
        const data = await res.json()
        setMessages(prev => [...prev, data])
        setReply('')
      } else {
        // optimistic update for dev
        setMessages(prev => [...prev, {
          sender: 'subscriber',
          body: reply,
          created_at: new Date().toISOString(),
        }])
        setReply('')
      }
    } catch {
      setMessages(prev => [...prev, {
        sender: 'subscriber',
        body: reply,
        created_at: new Date().toISOString(),
      }])
      setReply('')
    } finally {
      setSending(false)
    }
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px' }}>
        <button
          onClick={onBack}
          style={{
            background: 'none',
            border: 'none',
            fontSize: '20px',
            cursor: 'pointer',
            color: '#FF6B35',
          }}
        >
          ←
        </button>
        <div>
          <div style={{ fontWeight: '600', fontSize: '15px' }}>{ticket.subject}</div>
          <StatusBadge status={ticket.status} />
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '16px' }}>
        {messages.map((msg, i) => {
          const isMe = msg.sender === 'subscriber'
          return (
            <div key={i} style={{ display: 'flex', justifyContent: isMe ? 'flex-end' : 'flex-start' }}>
              <div style={{
                maxWidth: '80%',
                background: isMe ? '#FF6B35' : '#f4f6f8',
                color: isMe ? 'white' : '#1a1a2e',
                borderRadius: isMe ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
                padding: '10px 14px',
                fontSize: '14px',
                lineHeight: '1.5',
              }}>
                <div>{msg.body}</div>
                <div style={{ fontSize: '11px', opacity: 0.7, marginTop: '4px', textAlign: isMe ? 'right' : 'left' }}>
                  {formatDate(msg.created_at)}
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {ticket.status !== 'closed' && (
        <div style={{ display: 'flex', gap: '8px' }}>
          <input
            type="text"
            placeholder="উত্তর লিখুন..."
            value={reply}
            onChange={e => setReply(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSend()}
          />
          <button
            onClick={handleSend}
            disabled={sending || !reply.trim()}
            style={{
              background: '#FF6B35',
              color: 'white',
              border: 'none',
              borderRadius: '10px',
              padding: '14px 18px',
              cursor: sending ? 'not-allowed' : 'pointer',
              fontSize: '18px',
              flexShrink: 0,
            }}
          >
            →
          </button>
        </div>
      )}
    </div>
  )
}

export default function Support() {
  const [tickets, setTickets] = useState([])
  const [showForm, setShowForm] = useState(false)
  const [selectedCategory, setSelectedCategory] = useState('')
  const [description, setDescription] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [activeTicket, setActiveTicket] = useState(null)

  useEffect(() => {
    const token = localStorage.getItem('whisp_sub_token')
    const fetchTickets = async () => {
      try {
        const res = await fetch('/api/tickets', {
          headers: { Authorization: `Bearer ${token}` },
        })
        if (res.ok) {
          const data = await res.json()
          setTickets(data.items || data || MOCK_TICKETS)
        } else {
          setTickets(MOCK_TICKETS)
        }
      } catch {
        setTickets(MOCK_TICKETS)
      }
    }
    fetchTickets()
  }, [])

  const handleSubmit = async () => {
    if (!selectedCategory || !description.trim()) return
    const token = localStorage.getItem('whisp_sub_token')
    setSubmitting(true)
    try {
      const cat = CATEGORIES.find(c => c.id === selectedCategory)
      const res = await fetch('/api/tickets', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          subject: cat?.label || selectedCategory,
          category: selectedCategory,
          body: description,
        }),
      })
      if (res.ok) {
        const newTicket = await res.json()
        setTickets(prev => [{ ...newTicket, messages: [] }, ...prev])
      } else {
        // optimistic
        const cat = CATEGORIES.find(c => c.id === selectedCategory)
        setTickets(prev => [{
          id: `t_${Date.now()}`,
          subject: cat?.label || selectedCategory,
          category: selectedCategory,
          status: 'open',
          created_at: new Date().toISOString(),
          messages: [{ sender: 'subscriber', body: description, created_at: new Date().toISOString() }],
        }, ...prev])
      }
      setShowForm(false)
      setSelectedCategory('')
      setDescription('')
    } catch {
      alert('অভিযোগ জমা দেওয়া যায়নি। আবার চেষ্টা করুন।')
    } finally {
      setSubmitting(false)
    }
  }

  if (activeTicket) {
    return (
      <div>
        <div className="page-header-bar">
          <div style={{ fontSize: '20px', fontWeight: '700' }}>সাহায্য</div>
        </div>
        <div className="page-content">
          <TicketThread ticket={activeTicket} onBack={() => setActiveTicket(null)} />
        </div>
      </div>
    )
  }

  return (
    <div>
      <div className="page-header-bar">
        <div style={{ fontSize: '20px', fontWeight: '700' }}>সাহায্য</div>
      </div>

      <div className="page-content">
        {/* Quick help cards */}
        <div style={{ marginBottom: '24px' }}>
          <div style={{ fontSize: '15px', fontWeight: '600', marginBottom: '12px' }}>
            কী সমস্যা হচ্ছে?
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
            {CATEGORIES.map(cat => (
              <div
                key={cat.id}
                onClick={() => {
                  setSelectedCategory(cat.id)
                  setShowForm(true)
                }}
                className="card"
                style={{
                  cursor: 'pointer',
                  textAlign: 'center',
                  padding: '16px 12px',
                  transition: 'all 0.15s',
                }}
              >
                <div style={{ fontSize: '28px', marginBottom: '8px' }}>{cat.emoji}</div>
                <div style={{ fontSize: '13px', fontWeight: '500' }}>{cat.label}</div>
              </div>
            ))}
          </div>
        </div>

        {/* New complaint button */}
        {!showForm && (
          <button
            className="btn-outline"
            onClick={() => setShowForm(true)}
            style={{ marginBottom: '24px' }}
          >
            + নতুন অভিযোগ করুন
          </button>
        )}

        {/* Complaint form */}
        {showForm && (
          <div className="card" style={{ marginBottom: '24px' }}>
            <div style={{ fontSize: '15px', fontWeight: '600', marginBottom: '14px' }}>
              নতুন অভিযোগ
            </div>

            <div style={{ marginBottom: '12px' }}>
              <label>বিষয়</label>
              <select
                value={selectedCategory}
                onChange={e => setSelectedCategory(e.target.value)}
                style={{
                  border: '2px solid #e5e7eb',
                  borderRadius: '10px',
                  padding: '14px 16px',
                  fontFamily: 'inherit',
                  fontSize: '15px',
                  width: '100%',
                  outline: 'none',
                  background: 'white',
                  color: selectedCategory ? '#1a1a2e' : '#9ca3af',
                  cursor: 'pointer',
                }}
              >
                <option value="">বিষয় বেছে নিন</option>
                {CATEGORIES.map(cat => (
                  <option key={cat.id} value={cat.id}>{cat.label}</option>
                ))}
              </select>
            </div>

            <div style={{ marginBottom: '16px' }}>
              <label>বিবরণ</label>
              <textarea
                placeholder="আপনার সমস্যা বিস্তারিত লিখুন..."
                value={description}
                onChange={e => setDescription(e.target.value)}
                rows={4}
                style={{
                  border: '2px solid #e5e7eb',
                  borderRadius: '10px',
                  padding: '14px 16px',
                  fontFamily: 'inherit',
                  fontSize: '15px',
                  width: '100%',
                  outline: 'none',
                  resize: 'vertical',
                  color: '#1a1a2e',
                  background: 'white',
                  transition: 'border-color 0.2s',
                }}
                onFocus={e => e.target.style.borderColor = '#FF6B35'}
                onBlur={e => e.target.style.borderColor = '#e5e7eb'}
              />
            </div>

            <div style={{ display: 'flex', gap: '10px' }}>
              <button
                className="btn-outline"
                onClick={() => {
                  setShowForm(false)
                  setSelectedCategory('')
                  setDescription('')
                }}
                style={{ flex: 1 }}
              >
                বাতিল
              </button>
              <button
                className="btn-primary"
                onClick={handleSubmit}
                disabled={submitting || !selectedCategory || !description.trim()}
                style={{ flex: 1 }}
              >
                {submitting ? 'পাঠানো হচ্ছে...' : 'জমা দিন'}
              </button>
            </div>
          </div>
        )}

        {/* Tickets list */}
        <div>
          <div style={{ fontSize: '15px', fontWeight: '600', marginBottom: '12px' }}>
            আমার অভিযোগ
          </div>
          {tickets.length === 0 ? (
            <div className="card" style={{ textAlign: 'center', color: '#6b7280', fontSize: '14px' }}>
              কোনো অভিযোগ নেই
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {tickets.map(ticket => (
                <div
                  key={ticket.id}
                  className="card"
                  onClick={() => setActiveTicket(ticket)}
                  style={{ cursor: 'pointer', padding: '14px 16px' }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontWeight: '500', fontSize: '15px', marginBottom: '4px' }}>
                        {ticket.subject}
                      </div>
                      <div style={{ fontSize: '12px', color: '#9ca3af' }}>
                        {formatDate(ticket.created_at)}
                      </div>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
                      <StatusBadge status={ticket.status} />
                      <span style={{ color: '#9ca3af', fontSize: '16px' }}>›</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
