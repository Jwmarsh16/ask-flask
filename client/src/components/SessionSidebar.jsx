// client/src/components/SessionSidebar.jsx
import { useEffect, useState, useCallback } from 'react'

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

  // LocalStorage keys // (unchanged)
  const LS_SESSIONS = 'askFlaskSessions'
  const LS_SESSION_ID = 'askFlaskSessionId'

  // NEW: robust UUID generator with fallback // <-- FIX: ensure we can always create a non-null id
  const genId = useCallback(() => {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
      const r = (Math.random() * 16) | 0
      const v = c === 'x' ? r : (r & 0x3) | 0x8
      return v.toString(16)
    })
  }, [])

  const readSessions = () => {
    const raw = localStorage.getItem(LS_SESSIONS)
    try { return raw ? JSON.parse(raw) : [] } catch { return [] }
  }
  const writeSessions = (list) => localStorage.setItem(LS_SESSIONS, JSON.stringify(list))

  // Initialize from LocalStorage, but guarantee a valid non-null session id. // <-- FIX: prevent null id seeding
  useEffect(() => {
    const list = readSessions()
    if (list.length === 0) {
      // Ensure we have a current session id persisted // <-- FIX
      let id = localStorage.getItem(LS_SESSION_ID)
      if (!id) {
        id = genId() // <-- FIX
        localStorage.setItem(LS_SESSION_ID, id) // <-- FIX
      }
      const seed = [{ id, title: 'New session', created_at: new Date().toISOString() }]
      setSessions(seed)
      writeSessions(seed)
      // Inform parent if it doesn't already have a session selected // <-- FIX (defensive)
      onSelectSession?.(id)
    } else {
      // Filter out any corrupted entries lacking an id // <-- FIX
      const sanitized = list.filter(s => !!s?.id)
      setSessions(sanitized)
      if (sanitized.length !== list.length) writeSessions(sanitized)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [genId])

  const handleCreate = () => {
    const id = genId() // <-- FIX: use robust generator
    const entry = { id, title: 'New session', created_at: new Date().toISOString() }
    const next = [entry, ...sessions]
    setSessions(next)
    writeSessions(next)
    localStorage.setItem(LS_SESSION_ID, id) // <-- FIX: keep LS in sync
    onSelectSession?.(id)
  }

  const handleDelete = (id) => {
    const next = sessions.filter(s => s.id !== id)
    setSessions(next)
    writeSessions(next)
    if (id === sessionId) {
      const replacement = next[0]?.id
      if (replacement) {
        localStorage.setItem(LS_SESSION_ID, replacement) // <-- FIX: sync LS on delete
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
          <li key={s.id || Math.random()} style={{ // <-- FIX: guard key if something is malformed
            display: 'grid',
            gridTemplateColumns: '1fr auto',
            alignItems: 'center',
            gap: 6,
            padding: 6,
            borderRadius: 6,
            background: s.id === sessionId ? 'rgba(255,255,255,0.06)' : 'transparent',
            cursor: 'pointer'
          }}>
            <div onClick={() => s.id && onSelectSession?.(s.id)}> {/* <-- FIX: don't pass null */}
              <div style={{ fontSize: 13, fontWeight: 600 }}>{s.title || 'Untitled'}</div>
              <div style={{ fontSize: 11, opacity: 0.7 }}>
                {(s.id ? s.id.slice(0, 8) : 'new')}… {/* <-- FIX: null-safe slice */}
              </div>
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <button onClick={() => s.id && handleRename(s.id)} title="Rename">✎</button> {/* <-- FIX: guard null */}
              <button onClick={() => s.id && handleDelete(s.id)} title="Delete">🗑</button> {/* <-- FIX: guard null */}
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
