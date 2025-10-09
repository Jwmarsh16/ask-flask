// client/src/components/SessionSidebar.jsx
import { useEffect, useMemo, useState } from 'react'

/**
 * Minimal Session sidebar (LocalStorage-first).
 * - Lists local sessions (id + optional title)
 * - Create/select/delete a session
 * - Placeholder Export buttons (will call API in next pass)
 *
 * Once BE routes are wired, we can swap the data source to:
 *   GET  /api/sessions
 *   POST /api/sessions
 *   DELETE /api/sessions/:id
 *   GET  /api/sessions/:id/export?format=json|md
 */
export default function SessionSidebar({ sessionId, onSelectSession }) {
  const [sessions, setSessions] = useState([])

  // LocalStorage helpers (namespaced) // <-- ADDED
  const LS_SESSIONS = 'askFlaskSessions'
  const LS_SESSION_ID = 'askFlaskSessionId'

  const readSessions = () => {
    const raw = localStorage.getItem(LS_SESSIONS)
    try { return raw ? JSON.parse(raw) : [] } catch { return [] }
  }
  const writeSessions = (list) => localStorage.setItem(LS_SESSIONS, JSON.stringify(list))

  // Init from LocalStorage once. // <-- ADDED
  useEffect(() => {
    const list = readSessions()
    if (list.length === 0) {
      const id = localStorage.getItem(LS_SESSION_ID)
      const seed = [{ id, title: 'New session', created_at: new Date().toISOString() }]
      setSessions(seed)
      writeSessions(seed)
    } else {
      setSessions(list)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleCreate = () => {
    const id = (crypto?.randomUUID?.() || Math.random().toString(36).slice(2) + Date.now().toString(36))
    const entry = { id, title: 'New session', created_at: new Date().toISOString() }
    const next = [entry, ...sessions]
    setSessions(next)
    writeSessions(next)
    onSelectSession?.(id)
  }

  const handleDelete = (id) => {
    const next = sessions.filter(s => s.id !== id)
    setSessions(next)
    writeSessions(next)
    // If deleting current session, pick another or create a fresh one. // <-- ADDED
    if (id === sessionId) {
      const replacement = next[0]?.id
      if (replacement) {
        onSelectSession?.(replacement)
      } else {
        handleCreate()
      }
    }
  }

  const handleRename = (id) => {
    const title = prompt('Session title:')
    if (title === null) return
    const next = sessions.map(s => (s.id === id ? { ...s, title } : s))
    setSessions(next)
    writeSessions(next)
  }

  const disabled = !sessionId

  const exportDisabledTooltip = 'Export API will be wired next (server routes pending)'

  return (
    <div style={{ border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, padding: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <strong>Sessions</strong>
        <button onClick={handleCreate} title="Create a new session">＋</button>
      </div>
      <ul style={{ listStyle: 'none', padding: 0, margin: 0, maxHeight: 360, overflowY: 'auto' }}>
        {sessions.map(s => (
          <li key={s.id} style={{
            display: 'grid',
            gridTemplateColumns: '1fr auto',
            alignItems: 'center',
            gap: 6,
            padding: 6,
            borderRadius: 6,
            background: s.id === sessionId ? 'rgba(255,255,255,0.06)' : 'transparent',
            cursor: 'pointer'
          }}>
            <div onClick={() => onSelectSession?.(s.id)}>
              <div style={{ fontSize: 13, fontWeight: 600 }}>{s.title || 'Untitled'}</div>
              <div style={{ fontSize: 11, opacity: 0.7 }}>{s.id.slice(0, 8)}…</div>
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <button onClick={() => handleRename(s.id)} title="Rename">✎</button>
              <button onClick={() => handleDelete(s.id)} title="Delete">🗑</button>
            </div>
          </li>
        ))}
      </ul>

      <hr style={{ borderColor: 'rgba(255,255,255,0.08)', margin: '10px 0' }} />

      <div style={{ display: 'grid', gap: 6 }}>
        <button disabled={disabled} title={exportDisabledTooltip}>Export JSON</button>
        <button disabled={disabled} title={exportDisabledTooltip}>Export Markdown</button>
      </div>
    </div>
  )
}
