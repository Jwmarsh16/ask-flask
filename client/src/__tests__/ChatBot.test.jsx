// client/src/__tests__/ChatBot.test.jsx
import React from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import ChatBot from '../components/ChatBot.jsx'

const encoder = new TextEncoder()

function sseResponse(frames) {
  const stream = new ReadableStream({
    start(controller) {
      for (const obj of frames) {
        const chunk = `data: ${JSON.stringify(obj)}\n\n`
        controller.enqueue(encoder.encode(chunk))
      }
      controller.close()
    },
  })
  return new Response(stream, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
  })
}

function jsonResponse(body, init = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
}

beforeEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

test('renders and sends a message via non-stream path', async () => {
  global.fetch = vi.fn(async (url) => {
    const u = String(url)
    if (u.endsWith('/api/chat')) return jsonResponse({ reply: 'pong' })
    if (u.endsWith('/api/chat/stream')) return new Response('no stream', { status: 500 })
    return new Response('not found', { status: 404 })
  })

  render(React.createElement(ChatBot))

  const user = userEvent.setup()

  // Turn streaming OFF to force non-stream branch
  const streamToggle = screen.getByLabelText(/stream/i)
  if (streamToggle.checked) {
    await user.click(streamToggle)
  }

  const input = screen.getByPlaceholderText(/type a message/i)
  await user.type(input, 'hello')
  await user.click(screen.getByRole('button', { name: /send/i }))

  await screen.findByText(/pong/i)
})

test('streams tokens via SSE and renders combined text', async () => {
  global.fetch = vi.fn(async (url) => {
    const u = String(url)
    if (u.endsWith('/api/chat/stream')) {
      return sseResponse([{ request_id: 'req-1' }, { token: 'Hi' }, { token: '!' }, { done: true }])
    }
    if (u.endsWith('/api/chat')) return jsonResponse({ reply: 'fallback' })
    return new Response('not found', { status: 404 })
  })

  render(React.createElement(ChatBot))

  const user = userEvent.setup()

  // Ensure streaming is ON (default true)
  const streamToggle = screen.getByLabelText(/stream/i)
  if (!streamToggle.checked) {
    await user.click(streamToggle)
  }

  const input = screen.getByPlaceholderText(/type a message/i)
  await user.type(input, 'hi')
  await user.click(screen.getByRole('button', { name: /send/i }))

  await screen.findByText('Hi!', {}, { timeout: 2000 })
})

test('shows a friendly error when /api/chat returns error JSON', async () => {
  global.fetch = vi.fn(async (url) => {
    const u = String(url)
    if (u.endsWith('/api/chat')) return jsonResponse({ error: 'Too Many Requests' }, { status: 429 })
    if (u.endsWith('/api/chat/stream')) return new Response('no stream', { status: 500 })
    return new Response('not found', { status: 404 })
  })

  render(React.createElement(ChatBot))

  const user = userEvent.setup()

  // Non-stream for determinism
  const streamToggle = screen.getByLabelText(/stream/i)
  if (streamToggle.checked) {
    await user.click(streamToggle)
  }

  const input = screen.getByPlaceholderText(/type a message/i)
  await user.type(input, 'trigger error')
  await user.click(screen.getByRole('button', { name: /send/i }))

  await screen.findByText(/error:\s*too many requests/i)
})
