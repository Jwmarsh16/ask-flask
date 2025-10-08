// client/src/App.jsx
import './App.css'
import ChatBot from './components/ChatBot'

function App() {
  return (
    <div className="app-container">
      <div className="app-shell">
        <header className="app-header">{/* <-- CHANGED: polished title header */}
          <div className="app-logo" aria-hidden="true" />{/* <-- ADDED: decorative logo block */}
          <h1 className="app-title">Ask-Flask</h1>{/* <-- CHANGED: gradient text title */}
          {/* <p className="app-subtitle">AI chat with production-grade UX</p> */}{/* <-- ADDED: optional tagline, kept commented */}
        </header>
        <ChatBot />
      </div>
    </div>
  )
}

export default App
