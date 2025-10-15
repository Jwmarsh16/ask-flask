// client/src/components/SessionSidebar.jsx
import { useEffect, useRef, useState } from 'react' // <-- CHANGED: add useRef for one-time init guard

/**
 * Session sidebar wired to the backend Sessions API.
 * - Lists sessions from GET /api/sessions
 * - Create via POST /api/sessions
 * - Delete via DELETE /api/sessions/:id
 * - Export via GET /api/sessions/:id/export?format=json|md
 *
 * Notes:
 * - We still persist ONLY the active session id in LocalStorage
 *   under 'askFlaskSessionId' to survive reloads.
 * - Rename remains local-only (no backend endpoint yet). // <-- CHANGED: clarify behavior
 */
export default function SessionSidebar({ sessionId, onSelectSession }) {
  const [sessions, setSessions] = useState([]) // <-- CHANGED: now sourced from backend
  const initOnce = useRef(false) // <-- ADDED: ensure we only seed once on mount

  // LocalStorage key (unchanged)
  const LS_SESSION_ID = 'askFlaskSessionId'

  // Small helper: unified fetch with JSON/error handling // <-- ADDED: local API helper
  const api = async (path, options) => {
    const res = await fetch(`/api${path}`, {
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      ...options,
    })
    // Export endpoints return files; caller will handle them. // <-- ADDED
    if (options?.expectsBlob) return res
    const text = await res.text()
    const data = text ? JSON.parse(text) : null
    if (!res.ok) {
      const err = (data && (data.error || data.message)) || `HTTP ${res.status}`
      throw new Error(err)
    }
    return data
  }

  // Load sessions from backend, seed one if empty // <-- CHANGED: backend-first load
  const loadSessions = async () => {
    const list = await api('/sessions', { method: 'GET' })
    setSessions(list)
    const saved = localStorage.getItem(LS_SESSION_ID)
    // Decide which session to select // <-- ADDED: robust selection logic
    const found = list.find(s => s.id === saved)
    if (found) {
      if (!sessionId) onSelectSession?.(found.id) // keep parent in sync if not already selected
      return
    }
    if (list.length > 0) {
      const first = list[0].id
      localStorage.setItem(LS_SESSION_ID, first)
      if (!sessionId) onSelectSession?.(first)
      return
    }
    // No sessions exist -> create an initial one // <-- ADDED: seed server-side session
    const created = await api('/sessions', {
      method: 'POST',
      body: JSON.stringify({ title: 'New session' }),
    })
    localStorage.setItem(LS_SESSION_ID, created.id)
    onSelectSession?.(created.id)
    // Reflect on the list locally
    setSessions(prev => [created, ...prev])
  }

  // Initialize from backend once on mount // <-- CHANGED: switch from LocalStorage list to API
  useEffect(() => {
    if (initOnce.current) return
    initOnce.current = true
    loadSessions().catch(() => {
      // If backend is temporarily unavailable, keep an empty list and
      // allow user to retry via the "+" button. // <-- ADDED: graceful fallback
      setSessions([])
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleCreate = async () => {
    try {
      const created = await api('/sessions', {
        method: 'POST',
        body: JSON.stringify({ title: 'New session' }), // <-- CHANGED: create on server
      })
      setSessions(prev => [created, ...prev])
      localStorage.setItem(LS_SESSION_ID, created.id) // <-- CHANGED: keep LS in sync with active id
      onSelectSession?.(created.id)
    } catch (e) {
      alert(`Failed to create session: ${e.message}`) // <-- ADDED: user feedback
    }
  }

  const handleDelete = async (id) => {
    try {
      await api(`/sessions/${id}`, { method: 'DELETE' }) // <-- CHANGED: delete on server
      const next = sessions.filter(s => s.id !== id)
      setSessions(next)
      // If the active session was deleted, pick a replacement or create a fresh one
      if (id === sessionId) {
        const replacement = next[0]?.id
        if (replacement) {
          localStorage.setItem(LS_SESSION_ID, replacement) // <-- CHANGED: sync LS on delete
          onSelectSession?.(replacement)
        } else {
          await handleCreate() // seeds a new one and selects it
        }
      }
    } catch (e) {
      alert(`Failed to delete session: ${e.message}`) // <-- ADDED
    }
  }

  const handleRename = async (id) => {
    // No backend rename endpoint in current contract; keep local only for now. // <-- CHANGED: local-only rename
    const title = prompt('Session title:')
    if (title === null) return
    setSessions(prev => prev.map(s => (s.id === id ? { ...s, title } : s)))
    // TODO: When a rename route exists (e.g., PATCH /api/sessions/:id), call it here. // <-- TODO
  }

  const handleExport = async (format) => {
    if (!sessionId) return
    try {
      const res = await api(`/sessions/${sessionId}/export?format=${format}`, {
        method: 'GET',
        expectsBlob: true, // <-- ADDED: treat as binary
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const blob = await res.blob()
      // Try to parse filename from Content-Disposition, else fallback // <-- ADDED: nice filename
      const cd = res.headers.get('Content-Disposition') || ''
      const match = /filename="([^"]+)"/.exec(cd)
      const filename = match?.[1] || `session-export.${format}`
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      alert(`Failed to export: ${e.message}`) // <-- ADDED
    }
  }

  const disabled = !sessionId

  return (
    <div style={{ border: '1px solid rgba(255,255,255,0.08)', borderRadius: 8, padding: 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <strong>Sessions</strong>
        <button onClick={handleCreate} title="Create a new session">＋</button> {/* <-- CHANGED: now creates on server */}
      </div>
      <ul style={{ listStyle: 'none', padding: 0, margin: 0, maxHeight: 360, overflowY: 'auto' }}>
        {sessions.map(s => (
          <li key={s.id} style={{ // <-- CHANGED: keys guaranteed by server ids
            display: 'grid',
            gridTemplateColumns: '1fr auto',
            alignItems: 'center',
            gap: 6,
            padding: 6,
            borderRadius: 6,
            background: s.id === sessionId ? 'rgba(255,255,255,0.06)' : 'transparent',
            cursor: 'pointer'
          }}>
            <div onClick={() => onSelectSession?.(s.id)}> {/* <-- CHANGED: id is always defined */}
              <div style={{ fontSize: 13, fontWeight: 600 }}>{s.title || 'Untitled'}</div>
              <div style={{ fontSize: 11, opacity: 0.7 }}>
                {s.id.slice(0, 8)}… {/* <-- CHANGED: server guarantees id */}
              </div>
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <button onClick={() => handleRename(s.id)} title="Rename">✎</button> {/* <-- CHANGED: local-only rename */}
              <button onClick={() => handleDelete(s.id)} title="Delete">🗑</button> {/* <-- CHANGED: delete on server */}
            </div>
          </li>
        ))}
      </ul>

      <hr style={{ borderColor: 'rgba(255,255,255,0.08)', margin: '10px 0' }} />

      <div style={{ display: 'grid', gap: 6 }}>
        <button disabled={disabled} onClick={() => handleExport('json')} title="Download JSON transcript">Export JSON</button> {/* <-- CHANGED: wire to API */}
        <button disabled={disabled} onClick={() => handleExport('md')} title="Download Markdown transcript">Export Markdown</button> {/* <-- CHANGED: wire to API */}
      </div>
    </div>
  )
}
