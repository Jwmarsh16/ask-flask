// client/src/App.jsx
import './App.css'
import ChatBot from './components/ChatBot'
import SessionSidebar from './components/SessionSidebar' // <-- sidebar component import

import { useEffect, useState, useCallback } from 'react' // <-- React hooks for sessionId persistence

function App() {
  const [sessionId, setSessionId] = useState(null) // hold current session id

  // Initialize sessionId from LocalStorage only; if none, leave null and let
  // SessionSidebar create the first session on the server and report back.
  useEffect(() => {
    const stored = localStorage.getItem('askFlaskSessionId')
    setSessionId(stored || null)
  }, [])

  // Update LocalStorage when the user selects/creates a different session.
  const handleSelectSession = useCallback((id) => {
    setSessionId(id)
    localStorage.setItem('askFlaskSessionId', id)
  }, [])

  return (
    <div className="app-container af-app-container">
      {/* af-* class added to hook into the new design system tokens in index.css */}
      <div className="app-shell af-app-shell">
        <header className="app-header af-app-header">
          {/* af-app-header allows us to style a proper product-style top bar in App.css */}
          <div className="app-logo af-app-logo" aria-hidden="true" />
          {/* decorative logo block (glow/orb) for visual identity */}
          <h1 className="app-title af-app-title">Ask-Flask</h1>
          {/* gradient text title; af-app-title will handle typography + spacing */}
          {/* <p className="app-subtitle af-app-subtitle">AI chat with production-grade UX</p> */}
          {/* optional tagline kept commented for now */}
        </header>

        {/* Main layout now controlled via CSS class instead of inline grid style */}
        <div className="app-main af-app-main">
          {/* af-app-main will define the 2-column grid using CSS, not inline styles */}
          <aside className="app-sidebar af-app-sidebar">
            {/* sidebar wrapper class so we can give it a glass panel and scroll behavior */}
            <SessionSidebar
              sessionId={sessionId}
              onSelectSession={handleSelectSession}
            />
          </aside>
          <main className="app-chat af-app-chat">
            {/* main chat area wrapper; styled as primary content panel */}
            <ChatBot
              sessionId={sessionId}
              onSelectSession={handleSelectSession} // allow ChatBot to create/select sessions
            />
          </main>
        </div>
      </div>
    </div>
  )
}

export default App
