// client/src/App.jsx
import './App.css'
import ChatBot from './components/ChatBot'
import SessionSidebar from './components/SessionSidebar' // <-- ADDED: sidebar component import

import { useEffect, useState, useCallback } from 'react' // <-- ADDED: state for sessionId persistence

function App() {
  const [sessionId, setSessionId] = useState(null) // <-- ADDED: hold current session id

  // Helper to generate a UUID if browser supports it; otherwise a fallback. // <-- ADDED
  const genId = useCallback(() => {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
    // Simple RFC4122-ish fallback (good enough until BE returns real IDs). // <-- ADDED
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
      const r = (Math.random() * 16) | 0
      const v = c === 'x' ? r : (r & 0x3) | 0x8
      return v.toString(16)
    })
  }, [])

  // Initialize sessionId from LocalStorage on first load. // <-- ADDED
  useEffect(() => {
    const stored = localStorage.getItem('askFlaskSessionId')
    if (stored) {
      setSessionId(stored)
    } else {
      const id = genId()
      localStorage.setItem('askFlaskSessionId', id)
      setSessionId(id)
    }
  }, [genId])

  // Update LocalStorage when the user selects/creates a different session. // <-- ADDED
  const handleSelectSession = useCallback((id) => {
    setSessionId(id)
    localStorage.setItem('askFlaskSessionId', id)
  }, [])

  return (
    <div className="app-container">
      <div className="app-shell">
        <header className="app-header">{/* <-- CHANGED: polished title header (kept) */}
          <div className="app-logo" aria-hidden="true" />{/* <-- ADDED: decorative logo block (kept) */}
          <h1 className="app-title">Ask-Flask</h1>{/* <-- CHANGED: gradient text title (kept) */}
          {/* <p className="app-subtitle">AI chat with production-grade UX</p> */}{/* <-- ADDED: optional tagline, kept commented */}
        </header>

        {/* Simple two-column layout without new CSS dependencies. */}
        <div className="app-main" style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: '16px' }}>
          <aside>
            <SessionSidebar
              sessionId={sessionId}                 // <-- ADDED: pass current session id
              onSelectSession={handleSelectSession}  // <-- ADDED: update handler
            />
          </aside>
          <main>
            {/* Passing sessionId is safe even if ChatBot ignores it today. */}
            <ChatBot sessionId={sessionId} />        {/* <-- ADDED: plumb session id to ChatBot (no behavior change yet) */}
          </main>
        </div>
      </div>
    </div>
  )
}

export default App
