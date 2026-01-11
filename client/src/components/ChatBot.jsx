// client/src/components/ChatBot.jsx
import React, { useEffect, useMemo, useRef, useState } from 'react'
import '../ChatBot.css'

// ✨ Markdown rendering + GFM + Prism highlighting
import ReactMarkdown from 'react-markdown' // render Markdown
import remarkGfm from 'remark-gfm' // GitHub-flavored Markdown
import Prism from 'prismjs' // syntax highlighter
import 'prismjs/components/prism-javascript' // common languages
import 'prismjs/components/prism-typescript'
import 'prismjs/components/prism-jsx'
import 'prismjs/components/prism-tsx'
import 'prismjs/components/prism-python'
import 'prismjs/components/prism-json'
import 'prismjs/components/prism-markup'
// import 'prismjs/themes/prism.css'                        // ❌ OLD: light theme (replaced)
import 'prismjs/themes/prism-tomorrow.css' // ✅ CHANGED: darker theme to match dark UI

// 👇 Robust API base resolution:
// - DEV: use VITE_API_BASE_URL or default to http://localhost:5555
// - PROD: use VITE_API_BASE_URL only if it's NOT localhost; otherwise same-origin ('')
const rawEnvBase = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '') // trim trailing slashes
const isDev = import.meta.env.DEV
const isLocalhost = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(rawEnvBase)
const API_BASE = isDev ? rawEnvBase || 'http://localhost:5555' : rawEnvBase && !isLocalhost ? rawEnvBase : '' // unchanged

export default function ChatBot({ sessionId, onSelectSession }) {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState(() => {
    const saved = localStorage.getItem('askFlaskMessages')
    return saved ? JSON.parse(saved) : []
  })
  const [isTyping, setIsTyping] = useState(false)
  const [model, setModel] = useState(() => localStorage.getItem('askFlaskModel') || 'gpt-3.5-turbo')
  const [streamEnabled, setStreamEnabled] = useState(() => {
    const saved = localStorage.getItem('askFlaskStream')
    return saved ? saved === 'true' : true
  })
  const [rateRemaining, setRateRemaining] = useState(null)
  const [newSessionLoading, setNewSessionLoading] = useState(false)

  const chatEndRef = useRef(null)
  const chatWindowRef = useRef(null)

  // Load server history whenever sessionId changes (kept)
  useEffect(() => {
    if (!sessionId) return
    let cancelled = false
    ;(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/sessions/${sessionId}`, {
          credentials: 'same-origin',
        })
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.json()
        const serverMsgs = Array.isArray(data?.messages) ? data.messages : []
        const mapped = serverMsgs.map((m) => ({
          role: m.role === 'assistant' ? 'assistant' : 'user',
          content: m.content || '',
          timestamp: (() => {
            const iso = m.created_at
            if (!iso) return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
            const d = new Date(iso)
            return isNaN(d.getTime())
              ? new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
              : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
          })(),
        }))
        if (!cancelled) setMessages(mapped)
        if (!cancelled) localStorage.setItem('askFlaskMessages', JSON.stringify(mapped))
      } catch {
        if (!cancelled) setMessages([])
      }
    })()
    return () => {
      cancelled = true
    }
  }, [sessionId])

  // Persist UI transcript + re-highlight code blocks (kept)
  useEffect(() => {
    localStorage.setItem('askFlaskMessages', JSON.stringify(messages))

    const el = chatEndRef.current
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ behavior: 'smooth' }) // ✅ CHANGED: guard for jsdom (no scrollIntoView)
    }

    if (chatWindowRef.current) Prism.highlightAllUnder(chatWindowRef.current)
  }, [messages])

  useEffect(() => {
    localStorage.setItem('askFlaskModel', model)
  }, [model])

  useEffect(() => {
    localStorage.setItem('askFlaskStream', String(streamEnabled))
  }, [streamEnabled])

  // Unified ErrorResponse -> friendly text (kept)
  const formatError = (err) => {
    if (!err || typeof err !== 'object') return 'Unexpected error.'
    const code = err.code ?? 500
    const requestId = err.request_id ? ` (Ref: ${err.request_id})` : ''
    switch (code) {
      case 400:
        return `Please check your input.${requestId}`
      case 413:
        return `Message is too long (max 4000 chars).${requestId}`
      case 429:
        return `Too many requests. Try again soon.${requestId}`
      case 503:
        return `Service temporarily unavailable. Please retry.${requestId}`
      default:
        return `Unexpected error.${requestId}`
    }
  }

  const sendMessage = async () => {
    const trimmed = input.trim()
    if (!trimmed) return

    const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    const userMessage = { role: 'user', content: trimmed, timestamp }

    setMessages((prev) => [...prev, userMessage])
    setInput('')
    setIsTyping(true)

    const hasStreams = typeof globalThis.ReadableStream !== 'undefined' // ✅ CHANGED: works in browser + jsdom/node
    if (streamEnabled && hasStreams) {
      await sendMessageStreaming(trimmed, timestamp)
    } else {
      await sendMessageNonStreaming(trimmed, timestamp)
    }
  }

  const sendMessageNonStreaming = async (trimmed, ts) => {
    try {
      const payload = {
        message: trimmed,
        model,
        session_id: sessionId || undefined,
      }
      const res = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(payload),
      })

      const rl = res.headers.get('X-RateLimit-Remaining')
      if (rl !== null) setRateRemaining(rl)

      const data = await res.json()

      let botContent = ''
      if (res.ok && typeof data?.reply === 'string') {
        botContent = data.reply
      } else {
        botContent = `Error: ${formatError({ ...(data || {}), code: res.status })}` // ✅ CHANGED: include HTTP status
      }

      const botMessage = {
        role: 'assistant',
        content: botContent,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      }
      setMessages((prev) => [...prev, botMessage])
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Network error. Please try again.', timestamp: ts },
      ])
    } finally {
      setIsTyping(false)
    }
  }

  const sendMessageStreaming = async (trimmed, ts) => {
    const startIndex = messages.length + 1
    setMessages((prev) => [...prev, { role: 'assistant', content: '', timestamp: ts }])

    try {
      const payload = {
        message: trimmed,
        model,
        session_id: sessionId || undefined,
      }
      const res = await fetch(`${API_BASE}/api/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(payload),
      })

      const rl = res.headers.get('X-RateLimit-Remaining')
      if (rl !== null) setRateRemaining(rl)

      if (!res.ok || !res.body) {
        setMessages((prev) => prev.slice(0, -1))
        return await sendMessageNonStreaming(trimmed, ts)
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const parts = buffer.split('\n\n')
        buffer = parts.pop() || ''

        for (const part of parts) {
          const line = part.trim()
          if (!line.startsWith('data:')) continue
          const jsonText = line.slice(5).trim()
          if (!jsonText) continue

          try {
            const evt = JSON.parse(jsonText)
            if (evt.token) {
              setMessages((prev) => {
                const next = [...prev]
                const idx = startIndex
                next[idx] = {
                  ...next[idx],
                  content: (next[idx].content || '') + evt.token,
                }
                return next
              })
            }
            if (evt.done) {
              setMessages((prev) => {
                const next = [...prev]
                const idx = startIndex
                next[idx] = {
                  ...next[idx],
                  timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
                }
                return next
              })
            }
            if (evt.error) {
              setMessages((prev) => {
                const next = [...prev]
                const idx = startIndex
                next[idx] = {
                  ...next[idx],
                  content: `Error: ${formatError(evt)}`,
                }
                return next
              })
            }
          } catch {
            setMessages((prev) => {
              const next = [...prev]
              const idx = startIndex
              next[idx] = {
                ...next[idx],
                content: (next[idx].content || '') + jsonText,
              }
              return next
            })
          }
        }
      }
    } catch {
      setMessages((prev) => prev.slice(0, -1))
      await sendMessageNonStreaming(trimmed, ts)
    } finally {
      setIsTyping(false)
    }
  }

  const handleClearChat = async () => {
    if (newSessionLoading) return
    setNewSessionLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/sessions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({}),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      const id = data?.id
      if (!id) throw new Error('Missing session id')

      setMessages([])
      localStorage.removeItem('askFlaskMessages')
      onSelectSession?.(id)
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: 'Could not create a new session. Please try again.',
          timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        },
      ])
    } finally {
      setNewSessionLoading(false)
    }
  }

  // Memoized Markdown components so copy buttons don’t re-create unnecessarily
  const markdownComponents = useMemo(() => {
    function CodeBlock({ inline, className, children, ...props }) {
      if (inline)
        return (
          <code className={className} {...props}>
            {children}
          </code>
        )

      const rawCode = String(children || '')

      const onCopy = async (e) => {
        const btn = e.currentTarget // ✅ CHANGED: capture before await (event can be cleared/preserved differently in tests)
        try {
          await navigator.clipboard.writeText(rawCode)
          btn.setAttribute('data-copied', 'true')
          setTimeout(() => btn.setAttribute('data-copied', 'false'), 1200)
        } catch {
          // clipboard may be blocked; no-op
        }
      }

      return (
        <div className="codeblock">
          <button className="copy-btn" onClick={onCopy} aria-label="Copy code">
            <span className="copy-default">Copy</span>
            <span className="copy-done">Copied!</span>
          </button>
          <pre className={className}>
            <code className={className} {...props}>
              {rawCode}
            </code>
          </pre>
        </div>
      )
    }

    return { code: CodeBlock }
  }, [])

  return (
    <React.Fragment>
      {/* ✅ CHANGED: reference React to satisfy classic JSX runtime in CI/test transforms */}
      <div className="chatbot-container">
        <div className="chat-header">
          <h2>Ask-Flask 🤖</h2>
          <div className="chat-controls">
            <div className="rate-pill" title="Requests remaining this window">
              Rate limit: {rateRemaining ?? '—'} left
            </div>
            <label className="stream-toggle">
              <input
                type="checkbox"
                checked={streamEnabled}
                onChange={(e) => setStreamEnabled(e.target.checked)}
              />
              Stream
            </label>
            <select value={model} onChange={(e) => setModel(e.target.value)} aria-label="Model">
              <option value="gpt-3.5-turbo">GPT-3.5</option>
              <option value="gpt-4">GPT-4</option>
            </select>
            <button
              type="button"
              onClick={handleClearChat}
              disabled={newSessionLoading}
              title="Create a brand-new session and clear the chat"
            >
              {newSessionLoading ? 'Creating…' : 'Clear Chat'}
            </button>
          </div>
        </div>

        <div className="chat-window" ref={chatWindowRef}>
          {messages.map((msg, idx) => (
            <div key={idx} className={`message ${msg.role === 'user' ? 'user' : 'bot'}`}>
              <div className="message-content">
                {msg.role === 'assistant' ? (
                  <ReactMarkdown className="markdown" remarkPlugins={[remarkGfm]} components={markdownComponents}>
                    {msg.content || ''}
                  </ReactMarkdown>
                ) : (
                  <span>{msg.content}</span>
                )}
              </div>
              <div className="timestamp">{msg.timestamp}</div>
            </div>
          ))}

          {isTyping && (
            <div className="message bot typing-indicator" aria-live="polite" aria-label="Assistant is typing">
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
            aria-label="Message input"
          />
          <button type="button" onClick={sendMessage} aria-label="Send message">
            Send
          </button>
        </div>
      </div>
    </React.Fragment>
  )
}
