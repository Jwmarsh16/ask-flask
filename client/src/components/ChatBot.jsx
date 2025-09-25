import { useEffect, useRef, useState, useMemo } from 'react'
import '../ChatBot.css'

// ✨ Markdown rendering + GFM + Prism highlighting
import ReactMarkdown from 'react-markdown'                 // render Markdown
import remarkGfm from 'remark-gfm'                         // GitHub-flavored Markdown
import Prism from 'prismjs'                                 // syntax highlighter
import 'prismjs/components/prism-javascript'               // common languages
import 'prismjs/components/prism-typescript'
import 'prismjs/components/prism-jsx'
import 'prismjs/components/prism-tsx'
import 'prismjs/components/prism-python'
import 'prismjs/components/prism-json'
import 'prismjs/components/prism-markup'
// import 'prismjs/themes/prism.css'                        // ❌ OLD: light theme (replaced)
import 'prismjs/themes/prism-tomorrow.css'                  // ✅ CHANGED: darker theme to match dark UI

// 👇 Robust API base resolution:
// - DEV: use VITE_API_BASE_URL or default to http://localhost:5555
// - PROD: use VITE_API_BASE_URL only if it's NOT localhost; otherwise same-origin ('')
const rawEnvBase = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/+$/, '')  // trim trailing slashes
const isDev = import.meta.env.DEV
const isLocalhost = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/i.test(rawEnvBase)
const API_BASE = isDev ? (rawEnvBase || 'http://localhost:5555') : (rawEnvBase && !isLocalhost ? rawEnvBase : '')  // unchanged

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
  const [streamEnabled, setStreamEnabled] = useState(() => {            // streaming toggle (default on)
    const saved = localStorage.getItem('askFlaskStream')
    return saved ? saved === 'true' : true
  })
  const [rateRemaining, setRateRemaining] = useState(null)              // <-- ADDED: track X-RateLimit-Remaining

  const chatEndRef = useRef(null)
  const chatWindowRef = useRef(null)                                    // scope Prism highlighting

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

    if (streamEnabled && 'ReadableStream' in window) {                  // choose streaming path
      await sendMessageStreaming(trimmed, timestamp)
    } else {
      await sendMessageNonStreaming(trimmed, timestamp)
    }
  }

  const sendMessageNonStreaming = async (trimmed, ts) => {               // non-stream flow
    try {
      const res = await fetch(`${API_BASE}/api/chat`, { // prod → same-origin; dev → localhost:5555
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: trimmed, model }),
      })

      // --- Rate limit header handling (JSON path) ---
      const rl = res.headers.get('X-RateLimit-Remaining')               // <-- ADDED: read header
      if (rl !== null) setRateRemaining(rl)                              // <-- ADDED: update state

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
      const res = await fetch(`${API_BASE}/api/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: trimmed, model }),
      })

      // --- Rate limit header handling (SSE path) ---
      const rl = res.headers.get('X-RateLimit-Remaining')               // <-- ADDED: read header before streaming
      if (rl !== null) setRateRemaining(rl)                              // <-- ADDED: update state

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
              // surface server-side stream error text
              setMessages((prev) => {
                const next = [...prev]
                const idx = startIndex
                next[idx] = {
                  ...next[idx],
                  content: `Error: ${evt.error}`
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
      const language = match ? match[1] : undefined
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
          <pre className={className}> {/* ✅ CHANGED: pass language class to <pre> so Prism theme rules apply */}
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
          {/* <-- ADDED: small pill showing remaining requests in current window */}
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

export default ChatBot
