'use client'
import { useCallback, useEffect, useState } from 'react'

const j = (url: string, method = 'GET', body?: any) =>
  fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined })
    .then(async (r) => { const d = await r.json().catch(() => ({})); if (!r.ok) throw new Error(d.detail || r.statusText); return d })

const COLORS: Record<string, string> = { sent: '#16a34a', opened: '#22c55e', clicked: '#4ade80', failed: '#dc2626', skipped: '#d97706', scheduled: '#2563eb', sending: '#60a5fa' }
const fmt = (s?: string) => (s ? new Date(s).toLocaleString() : '—')
const REPEAT: Record<string, string> = { none: '', daily: 'FREQ=DAILY', weekly: 'FREQ=WEEKLY', monthly: 'FREQ=MONTHLY' }

export default function Home() {
  const [stats, setStats] = useState<any>(null)
  const [health, setHealth] = useState<any>(null)
  const [tab, setTab] = useState('messages')
  const [filter, setFilter] = useState('')
  const [messages, setMessages] = useState<any[]>([])
  const [reminders, setReminders] = useState<any[]>([])
  const [contacts, setContacts] = useState<any[]>([])
  const [campaigns, setCampaigns] = useState<any[]>([])
  const [toast, setToast] = useState('')
  const [preview, setPreview] = useState('')
  const [form, setForm] = useState({ title: '', contact_id: '', campaign_id: '', start: '+2m', repeat: 'none', custom: '', vars: '' })
  const [newContact, setNewContact] = useState({ name: '', email: '', timezone: 'Asia/Kolkata' })

  const say = (m: string) => { setToast(m); setTimeout(() => setToast(''), 3500) }
  const refresh = useCallback(async () => {
    try {
      const [s, h, m, r, c, ca] = await Promise.all([
        j('/api/stats'), j('/api/health'), j('/api/messages' + (filter ? `?status=${filter}` : '')),
        j('/api/reminders'), j('/api/contacts'), j('/api/campaigns')])
      setStats(s); setHealth(h); setMessages(m); setReminders(r); setContacts(c); setCampaigns(ca)
    } catch { setHealth(null) }
  }, [filter])
  useEffect(() => { refresh(); const t = setInterval(refresh, 5000); return () => clearInterval(t) }, [refresh])

  const act = async (fn: () => Promise<any>, ok: string) => {
    try { await fn(); say(ok); refresh() } catch (e: any) { say('Error: ' + e.message) }
  }
  const createReminder = () => act(async () => {
    let vars = {}
    if (form.vars.trim()) { try { vars = JSON.parse(form.vars) } catch { throw new Error('Variables must be valid JSON, e.g. {"link":"https://..."}') } }
    await j('/api/reminders', 'POST', { title: form.title, contact_id: form.contact_id, campaign_id: form.campaign_id,
      start: form.start, rrule: form.custom || REPEAT[form.repeat] || null, vars })
  }, 'Reminder scheduled')

  const total = stats?.total_messages || 0
  return (
    <>
      <div className="top">
        <div><h1>✉ Email Automation &amp; Reminders</h1><small>Schedule · Send · Track</small></div>
        <div>
          <span className="pill" style={{ background: health ? (health.mode === 'live' ? '#16a34a' : '#d97706') : '#dc2626' }}>
            {health ? `${health.mode.toUpperCase()} MODE` : 'API OFFLINE'}</span>
        </div>
      </div>
      <div className="wrap">
        <div className="grid g4">
          {[['Delivered', stats?.delivered], ['Success rate', stats ? stats.success_rate + '%' : '—'], ['Active reminders', stats?.active_reminders],
            ['Failed', stats?.by_status?.failed]].map(([k, v]: any) => (
            <div className="card stat" key={k}><b>{v ?? '—'}</b><span>{k}</span></div>))}
        </div>
        <div className="card" style={{ marginTop: 14 }}>
          <b>Message status</b>
          <div className="bar">{Object.entries(stats?.by_status || {}).filter(([, n]: any) => n > 0).map(([k, n]: any) =>
            <div key={k} title={`${k}: ${n}`} style={{ width: `${(100 * n) / total}%`, background: COLORS[k] }} />)}</div>
          <div className="mute">{Object.entries(stats?.by_status || {}).filter(([, n]: any) => n > 0).map(([k, n]) => `${k} ${n}`).join(' · ') || 'No messages yet — click “Load demo data”.'}</div>
        </div>
        <div style={{ display: 'flex', gap: 8, margin: '14px 0', flexWrap: 'wrap' }}>
          <button onClick={() => act(() => j('/api/demo/seed', 'POST'), 'Demo data loaded')}>Load demo data</button>
          <button onClick={() => act(() => j('/api/run', 'POST'), 'Scheduler cycle executed')}>▶ Run scheduler now</button>
          <a href="/api/report.csv"><button className="ghost">⬇ Download CSV report</button></a>
        </div>

        <div className="grid g2">
          <div className="card form">
            <b>Schedule a reminder</b>
            <input placeholder="Title (e.g. Python Class - Day 6)" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
            <select value={form.contact_id} onChange={(e) => setForm({ ...form, contact_id: e.target.value })}>
              <option value="">Select contact…</option>{contacts.map((c) => <option key={c.id} value={c.id}>{c.name} — {c.email}</option>)}</select>
            <select value={form.campaign_id} onChange={(e) => setForm({ ...form, campaign_id: e.target.value })}>
              <option value="">Select campaign (template)…</option>{campaigns.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
            <input placeholder="Start: +2m, +1h, or 2026-12-01T19:00 (contact's local time)" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} />
            <select value={form.repeat} onChange={(e) => setForm({ ...form, repeat: e.target.value })}>
              <option value="none">Does not repeat</option><option value="daily">Daily</option><option value="weekly">Weekly</option><option value="monthly">Monthly</option></select>
            <input placeholder="Or custom RRULE, e.g. FREQ=WEEKLY;BYDAY=MO,WE;COUNT=6" value={form.custom} onChange={(e) => setForm({ ...form, custom: e.target.value })} />
            <textarea rows={2} placeholder='Template variables (JSON), e.g. {"link":"https://meet.example.com/x"}' value={form.vars} onChange={(e) => setForm({ ...form, vars: e.target.value })} />
            <button disabled={!form.title || !form.contact_id || !form.campaign_id} onClick={createReminder}>Schedule reminder</button>
          </div>
          <div className="card form">
            <b>Add contact</b>
            <input placeholder="Full name" value={newContact.name} onChange={(e) => setNewContact({ ...newContact, name: e.target.value })} />
            <input placeholder="Email" value={newContact.email} onChange={(e) => setNewContact({ ...newContact, email: e.target.value })} />
            <input placeholder="Timezone (IANA)" value={newContact.timezone} onChange={(e) => setNewContact({ ...newContact, timezone: e.target.value })} />
            <button disabled={!newContact.name || !newContact.email}
              onClick={() => act(async () => { await j('/api/contacts', 'POST', newContact); setNewContact({ ...newContact, name: '', email: '' }) }, 'Contact added')}>Add contact</button>
            <p className="mute" style={{ margin: 0 }}>Tip: dry-run mode saves emails to <code>outputs/outbox/</code> — nothing is really sent.</p>
          </div>
        </div>

        <div className="tabs">
          {['messages', 'reminders', 'contacts'].map((t) => <button key={t} className={tab === t ? 'on' : ''} onClick={() => setTab(t)}>{t[0].toUpperCase() + t.slice(1)}</button>)}
          {tab === 'messages' && <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="">All statuses</option>{Object.keys(COLORS).map((s) => <option key={s}>{s}</option>)}</select>}
        </div>
        <div className="card scroll">
          {tab === 'messages' && <table><thead><tr><th>Recipient</th><th>Campaign</th><th>Subject</th><th>Status</th><th>Scheduled</th><th>Note</th><th /></tr></thead><tbody>
            {messages.map((m) => <tr key={m.id}><td>{m.contact_name}<br /><span className="mute">{m.contact_email}</span></td><td>{m.campaign}</td><td>{m.subject}</td>
              <td><span className={'pill ' + m.status}>{m.status}</span></td><td>{fmt(m.scheduled_at_utc)}</td><td className="mute">{m.error || (m.attempts ? `${m.attempts} attempt(s)` : '')}</td>
              <td>{m.sent_at_utc && <button className="ghost" onClick={() => setPreview(`/api/messages/${m.id}/html`)}>View</button>}
                {['failed', 'skipped'].includes(m.status) && <button className="ghost" onClick={() => act(() => j(`/api/messages/${m.id}/retry`, 'POST'), 'Queued for retry')}>Retry</button>}</td></tr>)}
          </tbody></table>}
          {tab === 'reminders' && <table><thead><tr><th>Title</th><th>Contact</th><th>Campaign</th><th>Starts</th><th>Repeat</th><th>State</th><th /></tr></thead><tbody>
            {reminders.map((r) => <tr key={r.id}><td>{r.title}</td><td>{r.contact_name}</td><td>{r.campaign}</td><td>{fmt(r.start_at_utc)}</td><td><code>{r.rrule || 'once'}</code></td>
              <td>{r.active ? 'Active' : 'Done / paused'}</td>
              <td><button className="ghost" onClick={() => act(() => j(`/api/reminders/${r.id}?active=${!r.active}`, 'PATCH'), 'Updated')}>{r.active ? 'Pause' : 'Resume'}</button>
                <button className="ghost" onClick={() => act(() => j(`/api/reminders/${r.id}`, 'DELETE'), 'Deleted')}>Delete</button></td></tr>)}
          </tbody></table>}
          {tab === 'contacts' && <table><thead><tr><th>Name</th><th>Email</th><th>Timezone</th><th>Subscribed</th><th /></tr></thead><tbody>
            {contacts.map((c) => <tr key={c.id}><td>{c.name}</td><td>{c.email}</td><td>{c.timezone}</td><td>{c.unsubscribed ? 'No' : 'Yes'}</td>
              <td><button className="ghost" onClick={() => act(() => j(`/api/contacts/${c.id}/unsubscribe?value=${!c.unsubscribed}`, 'PATCH'), 'Updated')}>{c.unsubscribed ? 'Resubscribe' : 'Unsubscribe'}</button></td></tr>)}
          </tbody></table>}
        </div>
      </div>
      {preview && <div className="modal" onClick={() => setPreview('')}><iframe src={preview} title="Email preview" /></div>}
      {toast && <div className="toast">{toast}</div>}
    </>
  )
}
