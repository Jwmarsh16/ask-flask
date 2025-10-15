// client/src/components/ChatBot.jsx
import { useEffect, useRef, useState, useMemo } from 'react'
import '../ChatBot.css'

// ✨ Markdown rendering + GFM + Prism highlighting
import ReactMarkdown from 'react-markdown'                 // render Markdown
import remarkGfm from 'remark-gfm'                         // GitHub-flavored Markdown
import Prism from 'prismjs'                                // syntax highlighter
import 'prismjs/components/prism-javascript'               // common languages
import 'prismjs/components/prism-typescript'
import 'prismjs/components/prism-jsx'
import 'prismjs/components/prism-tsx'
import 'prismjs/components/prism-python'
import 'prismjs/components/prism-json'
import 'prismjs/components/prism-markup'
// import 'prismjs/themes/prism.css'                        // ❌ OLD: light theme (replaced)
import 'prismjs/themes/prism-tomorrow.css'                 // ✅ CHANGED: darker theme to match dark UI

// 👇 Robust API base resolution:
// - DEV: use VITE_API_BASE_URL or default to http://localhost:5555
// - PROD: use VITE_API_BASE_URL only if it's NOT localhost; otherwise same-origin ('')
const rawEnvBase = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')  // trim trailing slashes
const isDev = import.meta.env.DEV
const isLocalhost = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(rawEnvBase)
const API_BASE = isDev ? (rawEnvBase || 'http://localhost:5555') : (rawEnvBase && !isLocalhost ? rawEnvBase : '')  // unchanged

export default function ChatBot({ sessionId }) { // <-- CHANGED: accept sessionId (prop already plumbed)
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState(() => {
    const saved = localStorage.getItem('askFlaskMessages')
    return saved ? JSON.parse(saved) : []
  })
  const [isTyping, setIsTyping] = useState(false)
  const [model, setModel] = useState(
    () => localStorage.getItem('askFlaskModel') || 'gpt-3.5-turbo'
  )
  const [streamEnabled, setStreamEnabled] = useState(() => {            // streaming toggle (default on)
    const saved = localStorage.getItem('askFlaskStream')
    return saved ? saved === 'true' : true
  })
  const [rateRemaining, setRateRemaining] = useState(null)              // track X-RateLimit-Remaining (JSON + SSE)

  const chatEndRef = useRef(null)
  const chatWindowRef = useRef(null)                                    // scope Prism highlighting

  // 🔹 NEW: Load server history whenever sessionId changes
  useEffect(() => {
    if (!sessionId) return
    let cancelled = false
    ;(async () => {
      try {
        const res = await fetch(`${API_BASE}/api/sessions/${sessionId}`, { credentials: 'same-origin' }) // <-- ADDED: load history from server
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const data = await res.json()
        const serverMsgs = Array.isArray(data?.messages) ? data.messages : []
        // Map server message shape to UI shape (role/content/timestamp) // <-- ADDED: normalize server payload
        const mapped = serverMsgs.map(m => ({
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
        // Keep LocalStorage in sync to preserve offline/refresh UX // <-- ADDED
        if (!cancelled) localStorage.setItem('askFlaskMessages', JSON.stringify(mapped))
      } catch {
        if (!cancelled) setMessages([])
      }
    })()
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId])

  // Persist UI transcript (for refresh/offline continuity) // (existing)
  useEffect(() => {
    localStorage.setItem('askFlaskMessages', JSON.stringify(messages))
    scrollToBottom()
    // Re-highlight code blocks whenever messages change
    if (chatWindowRef.current) {
      Prism.highlightAllUnder(chatWindowRef.current)
    }
  }, [messages])

  useEffect(() => {
    localStorage.setItem('askFlaskModel', model)
  }, [model])

  useEffect(() => {
    localStorage.setItem('askFlaskStream', String(streamEnabled))       // persist toggle
  }, [streamEnabled])

  const scrollToBottom = () => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }

  // Unified ErrorResponse -> friendly text // (existing)
  const formatError = (err) => {
    if (!err || typeof err !== 'object') return 'Unexpected error.'
    const code = err.code ?? 500
    const requestId = err.request_id ? ` (Ref: ${err.request_id})` : ''
    switch (code) {
      case 400: return `Please check your input.${requestId}`
      case 413: return `Message is too long (max 4000 chars).${requestId}`
      case 429: return `Too many requests. Try again soon.${requestId}`
      case 503: return `Service temporarily unavailable. Please retry.${requestId}`
      default: return `Unexpected error.${requestId}`
    }
  }

  // 🔹 NEW: Build a rolling context inside the single ChatRequest.message
  // Backend only accepts one 'message' string (max 4000 chars), so we
  // serialize recent turns as "Context:" lines. This makes the model remember
  // prior details (e.g., your name) on the next turn. // <-- ADDED
  const buildContextMessage = (userText) => {
    const MAX_LEN = 4000 // enforced by ChatRequest DTO
    const recent = messages.slice(-12) // last ~12 turns to keep things snappy
    const ctxLines = recent.map(m => `${m.role === 'assistant' ? 'Assistant' : 'User'}: ${m.content}`)
    const base = `User: ${userText}`
    let ctx = ctxLines.join('\n')
    let composed = ctx ? `Context:\n${ctx}\n\n${base}` : base
    if (composed.length > MAX_LEN) {
      const allowance = Math.max(0, MAX_LEN - base.length - 20) // small buffer
      if (allowance > 0) {
        ctx = ctx.slice(-allowance) // keep the most recent part of context
        composed = `Context:\n${ctx}\n\n${base}`
      } else {
        composed = base.slice(0, MAX_LEN) // extreme case: very long user input
      }
    }
    return composed
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

    if (streamEnabled && 'ReadableStream' in window) {
      await sendMessageStreaming(trimmed, timestamp) // (existing)
    } else {
      await sendMessageNonStreaming(trimmed, timestamp) // (existing)
    }
  }

  const sendMessageNonStreaming = async (trimmed, ts) => {               // non-stream flow
    try {
      const payload = {
        message: buildContextMessage(trimmed), // <-- CHANGED: include rolling context
        model,
        session_id: sessionId || undefined,    // <-- existing: persist to active session
      }
      const res = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })

      // --- Rate limit header handling (JSON path) ---
      const rl = res.headers.get('X-RateLimit-Remaining')
      if (rl !== null) setRateRemaining(rl)

      const data = await res.json()

      let botContent = ''
      if (res.ok && typeof data?.reply === 'string') {
        botContent = data.reply
      } else {
        botContent = `Error: ${formatError(data)}`
      }

      const botMessage = {
        role: 'assistant',
        content: botContent,
        timestamp: new Date().toLocaleTimeString([], {
          hour: '2-digit',
          minute: '2-digit',
        }),
      }
      setMessages((prev) => [...prev, botMessage])
    } catch (_error) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Network error. Please try again.', timestamp: ts },
      ])
    } finally {
      setIsTyping(false)
    }
  }

  const sendMessageStreaming = async (trimmed, ts) => {                  // streaming flow
    // Insert a placeholder assistant message to progressively append tokens
    const startIndex = messages.length + 1 // index after pushing the user message above
    setMessages((prev) => [
      ...prev,
      { role: 'assistant', content: '', timestamp: ts }
    ])

    try {
      const payload = {
        message: buildContextMessage(trimmed), // <-- CHANGED: include rolling context
        model,
        session_id: sessionId || undefined,    // <-- existing: persist to active session
      }
      const res = await fetch(`${API_BASE}/api/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })

      // --- Rate limit header handling (SSE path) ---
      const rl = res.headers.get('X-RateLimit-Remaining')
      if (rl !== null) setRateRemaining(rl)

      if (!res.ok || !res.body) {
        // If streaming not available or failed, gracefully fall back
        return await sendMessageNonStreaming(trimmed, ts)
      }

      const reader = res.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buffer = ''

      // Read chunks and parse SSE "data: ..." frames separated by \n\n
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })

        const parts = buffer.split('\n\n')
        buffer = parts.pop() || '' // keep incomplete frame in buffer

        for (const part of parts) {
          const line = part.trim()
          if (!line.startsWith('data:')) continue
          const jsonText = line.slice(5).trim()
          if (!jsonText) continue

          try {
            const evt = JSON.parse(jsonText)
            if (evt.token) {
              // Append token to the last assistant message
              setMessages((prev) => {
                const next = [...prev]
                const idx = startIndex // index of placeholder assistant msg
                next[idx] = {
                  ...next[idx],
                  content: (next[idx].content || '') + evt.token
                }
                return next
              })
            }
            if (evt.done) {
              // finalize timestamp for the assistant message
              setMessages((prev) => {
                const next = [...prev]
                const idx = startIndex
                next[idx] = {
                  ...next[idx],
                  timestamp: new Date().toLocaleTimeString([], {
                    hour: '2-digit',
                    minute: '2-digit',
                  }),
                }
                return next
              })
            }
            if (evt.error) {
              // Friendly message using unified SSE error fields
              setMessages((prev) => {
                const next = [...prev]
                const idx = startIndex
                next[idx] = {
                  ...next[idx],
                  content: `Error: ${formatError(evt)}`
                }
                return next
              })
            }
          } catch {
            // If parsing fails, append raw text
            setMessages((prev) => {
              const next = [...prev]
              const idx = startIndex
              next[idx] = {
                ...next[idx],
                content: (next[idx].content || '') + jsonText
              }
              return next
            })
          }
        }
      }
    } catch (_err) {
      // Network or stream failure → fall back message
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Network error during streaming. Retrying...', timestamp: ts },
      ])
      await sendMessageNonStreaming(trimmed, ts)
    } finally {
      setIsTyping(false)
    }
  }

  const clearChat = () => {
    // For now, just clears UI + LocalStorage. Next step: create a new server session instead. // <-- NOTE
    setMessages([])
    localStorage.removeItem('askFlaskMessages')
  }

  // Memoized Markdown components so copy buttons don’t re-create unnecessarily
  const markdownComponents = useMemo(() => {
    function CodeBlock({ inline, className, children, ...props }) {
      // If inline code, render simple <code>
      if (inline) {
        return <code className={className} {...props}>{children}</code>
      }

      // Extract language from className like "language-js"
      const match = /language-(\w+)/.exec(className || '')
      const rawCode = String(children || '')

      const onCopy = async () => {
        try {
          await navigator.clipboard.writeText(rawCode)
          // Quick visual feedback by toggling a data attribute (CSS handles effect)
          const btn = document.activeElement
          if (btn) {
            btn.setAttribute('data-copied', 'true')
            setTimeout(() => btn.setAttribute('data-copied', 'false'), 1200)
          }
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
          <pre className={className}> {/* pass language class to <pre> so Prism theme rules apply */}
            <code className={className} {...props}>
              {rawCode}
            </code>
          </pre>
        </div>
      )
    }

    return {
      code: CodeBlock, // override code renderer for fenced blocks and inline code
    }
  }, [])

  return (
    <div className="chatbot-container">
      <div className="chat-header">
        <h2>Ask-Flask 🤖</h2>
        <div className="chat-controls">
          {/* small pill showing remaining requests in current window */}
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
          <select value={model} onChange={(e) => setModel(e.target.value)}>
            <option value="gpt-3.5-turbo">GPT-3.5</option>
            <option value="gpt-4">GPT-4</option>
          </select>
          <button onClick={clearChat}>Clear Chat</button>
        </div>
      </div>

      <div className="chat-window" ref={chatWindowRef}>
        {messages.map((msg, idx) => (
          <div key={idx} className={`message ${msg.role === 'user' ? 'user' : 'bot'}`}>
            <div className="message-content">
              {msg.role === 'assistant' ? (
                // Assistant replies now render as Markdown (safe by default; no raw HTML)
                <ReactMarkdown
                  className="markdown"
                  remarkPlugins={[remarkGfm]}
                  components={markdownComponents}
                >
                  {msg.content || ''}
                </ReactMarkdown>
              ) : (
                // User messages remain plain text for now
                <span>{msg.content}</span>
              )}
            </div>
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
