// client/src/components/ChatBot.jsx

import { useEffect, useRef, useState } from 'react'
import '../ChatBot.css'

// 👇 Robust API base resolution:
// - DEV: use VITE_API_BASE_URL or default to http://localhost:5555
// - PROD: use VITE_API_BASE_URL only if it's NOT localhost; otherwise same-origin ('')
const rawEnvBase = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')  // trim trailing slashes
const isDev = import.meta.env.DEV
const isLocalhost = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(rawEnvBase)
const API_BASE = isDev ? (rawEnvBase || 'http://localhost:5555') : (rawEnvBase && !isLocalhost ? rawEnvBase : '')  // <-- changed

function ChatBot() {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState(() => {
    const saved = localStorage.getItem('askFlaskMessages')
    return saved ? JSON.parse(saved) : []
  })
  const [isTyping, setIsTyping] = useState(false)
  const [model, setModel] = useState(
    () => localStorage.getItem('askFlaskModel') || 'gpt-3.5-turbo'
  )
  const chatEndRef = useRef(null)

  useEffect(() => {
    localStorage.setItem('askFlaskMessages', JSON.stringify(messages))
    scrollToBottom()
  }, [messages])

  useEffect(() => {
    localStorage.setItem('askFlaskModel', model)
  }, [model])

  const scrollToBottom = () => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  const sendMessage = async () => {
    const trimmed = input.trim()
    if (!trimmed) return

    const timestamp = new Date().toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    })
    const userMessage = { role: 'user', content: trimmed, timestamp }

    setMessages((prev) => [...prev, userMessage])
    setInput('')
    setIsTyping(true)

    try {
      const res = await fetch(`${API_BASE}/api/chat`, { // prod → same-origin; dev → localhost:5555
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: trimmed, model }),
      })

      const data = await res.json()

      const botContent =
        typeof data?.reply === 'string'
          ? data.reply
          : data?.error
          ? `Error: ${data.error}`
          : 'Something went wrong!'

      const botMessage = {
        role: 'assistant',
        content: botContent,
        timestamp: new Date().toLocaleTimeString([], {
          hour: '2-digit',
          minute: '2-digit',
        }),
      }
      setMessages((prev) => [...prev, botMessage])
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Network error. Please try again.', timestamp },
      ])
    } finally {
      setIsTyping(false)
    }
  }

  const clearChat = () => {
    setMessages([])
    localStorage.removeItem('askFlaskMessages')
  }

  return (
    <div className="chatbot-container">
      <div className="chat-header">
        <h2>Ask-Flask 🤖</h2>
        <div className="chat-controls">
          <select value={model} onChange={(e) => setModel(e.target.value)}>
            <option value="gpt-3.5-turbo">GPT-3.5</option>
            <option value="gpt-4">GPT-4</option>
          </select>
          <button onClick={clearChat}>Clear Chat</button>
        </div>
      </div>

      <div className="chat-window">
        {messages.map((msg, idx) => (
          <div key={idx} className={`message ${msg.role === 'user' ? 'user' : 'bot'}`}>
            <div className="message-content">{msg.content}</div>
            <div className="timestamp">{msg.timestamp}</div>
          </div>
        ))}

        {isTyping && (
          <div className="message bot typing-indicator">
            <span className="dot"></span>
            <span className="dot"></span>
            <span className="dot"></span>
          </div>
        )}

        <div ref={chatEndRef} />
      </div>

      <div className="input-container">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a message..."
          onKeyDown={(e) => e.key === 'Enter' && sendMessage()}
        />
        <button onClick={sendMessage}>Send</button>
      </div>
    </div>
  )
}

export default ChatBot
