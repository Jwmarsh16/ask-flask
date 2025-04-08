import { useEffect, useRef, useState } from 'react'
import '../ChatBot.css'

function ChatBot() {
  const [input, setInput] = useState('')
  const [messages, setMessages] = useState(() => {
    const saved = localStorage.getItem('askFlaskMessages')
    return saved ? JSON.parse(saved) : []
  })
  const [isTyping, setIsTyping] = useState(false)
  const [model, setModel] = useState(() => localStorage.getItem('askFlaskModel') || 'gpt-3.5-turbo')
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
    if (!input.trim()) return

    const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    const userMessage = { role: 'user', content: input, timestamp }
    const newMessages = [...messages, userMessage]
    setMessages(newMessages)
    setInput('')
    setIsTyping(true)

    try {
      const res = await fetch('http://localhost:5000/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: input, model }),
      })

      const data = await res.json()
      const botMessage = {
        role: 'assistant',
        content: data.reply,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      }
      setMessages((prev) => [...prev, botMessage])
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: 'Something went wrong!', timestamp },
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
          <div
            key={idx}
            className={`message ${msg.role === 'user' ? 'user' : 'bot'}`}
          >
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
