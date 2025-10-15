// client/src/App.jsx
import './App.css'
import ChatBot from './components/ChatBot'
import SessionSidebar from './components/SessionSidebar' // <-- ADDED (kept): sidebar component import

import { useEffect, useState, useCallback } from 'react' // <-- ADDED (kept): state for sessionId persistence

function App() {
  const [sessionId, setSessionId] = useState(null) // <-- ADDED (kept): hold current session id

  // REMOVED: local UUID seeding (genId) to avoid mismatch with backend-created IDs.
  // The Sessions API now seeds the first session if none exist, and we persist
  // only the active id that the server returns. // <-- CHANGED: defer seeding to server

  // Initialize sessionId from LocalStorage only; if none, leave null and let
  // SessionSidebar create the first session on the server and report back. // <-- CHANGED: do not pre-seed locally
  useEffect(() => {
    const stored = localStorage.getItem('askFlaskSessionId')
    setSessionId(stored || null) // <-- CHANGED: avoid generating a fake id
  }, []) // <-- CHANGED: remove genId dependency

  // Update LocalStorage when the user selects/creates a different session. // (unchanged)
  const handleSelectSession = useCallback((id) => {
    setSessionId(id)
    localStorage.setItem('askFlaskSessionId', id)
  }, [])

  return (
    <div className="app-container">
      <div className="app-shell">
        <header className="app-header">{/* <-- CHANGED (kept): polished title header */}
          <div className="app-logo" aria-hidden="true" />{/* <-- ADDED (kept): decorative logo block */}
          <h1 className="app-title">Ask-Flask</h1>{/* <-- CHANGED (kept): gradient text title */}
          {/* <p className="app-subtitle">AI chat with production-grade UX</p> */}{/* <-- ADDED (kept): optional tagline */}
        </header>

        {/* Simple two-column layout without new CSS dependencies. */}
        <div className="app-main" style={{ display: 'grid', gridTemplateColumns: '260px 1fr', gap: '16px' }}>
          <aside>
            <SessionSidebar
              sessionId={sessionId}                 // <-- ADDED (kept): pass current session id
              onSelectSession={handleSelectSession}  // <-- ADDED (kept): update handler
            />
          </aside>
          <main>
            {/* Pass the session switcher so ChatBot can create + select a new session. */}
            <ChatBot
              sessionId={sessionId}
              onSelectSession={handleSelectSession}  // <-- ADDED: allow ChatBot to select new session
            />
          </main>
        </div>
      </div>
    </div>
  )
}

export default App
