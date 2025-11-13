// client/src/__tests__/ChatBot.test.jsx
// Purpose: Frontend tests for ChatBot.jsx covering non-stream + stream flows.
// Notes:
// - We mock global.fetch to avoid real network calls.
// - We assert UI behavior (message render) rather than implementation details.

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import ChatBot from '../components/ChatBot.jsx'

const encoder = new TextEncoder()

function sseResponse(frames) {
  // frames: array of objects that will be stringified per SSE "data: ...\n\n"
  const stream = new ReadableStream({
    start(controller) {
      for (const obj of frames) {
        const chunk = `data: ${JSON.stringify(obj)}\n\n`
        controller.enqueue(encoder.encode(chunk))
      }
      controller.close()
    }
  })
  return new Response(stream, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream; charset=utf-8' }
  })
}

function jsonResponse(body, init = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
    ...init
  })
}

beforeEach(() => {
  vi.restoreAllMocks()                  // ✅ Reset mocks between tests
  localStorage.clear()                  // ✅ Keep tests isolated
})

test('renders and sends a message via non-stream path', async () => {
  // Mock fetch: non-stream endpoint
  global.fetch = vi.fn(async (url, options) => {
    const u = String(url)
    if (u.endsWith('/api/chat')) {
      // Return a simple JSON reply
      return jsonResponse({ reply: 'pong' })
    }
    if (u.endsWith('/api/chat/stream')) {
      // Make stream fail -> component falls back to non-stream
      return new Response('no stream', { status: 500 })
    }
    return new Response('not found', { status: 404 })
  })

  render(<ChatBot />)

  // Turn streaming OFF to force non-stream branch
  const streamToggle = screen.getByLabelText(/stream/i)
  if (streamToggle.checked) {
    await userEvent.click(streamToggle) // uncheck
  }

  const input = screen.getByPlaceholderText(/type a message/i)
  await userEvent.type(input, 'hello')
  await userEvent.click(screen.getByRole('button', { name: /send/i }))

  // Expect assistant message 'pong' to appear
  await screen.findByText(/pong/i)
})

test('streams tokens via SSE and renders combined text', async () => {
  // Mock fetch: stream endpoint emits tokens "Hi" + "!"
  global.fetch = vi.fn(async (url, options) => {
    const u = String(url)
    if (u.endsWith('/api/chat/stream')) {
      return sseResponse([
        { request_id: 'req-1' },
        { token: 'Hi' },
        { token: '!' },
        { done: true }
      ])
    }
    if (u.endsWith('/api/chat')) {
      // Fallback shouldn't be used here, but return something harmless
      return jsonResponse({ reply: 'fallback' })
    }
    return new Response('not found', { status: 404 })
  })

  render(<ChatBot />)

  // Ensure streaming is ON (default true)
  const streamToggle = screen.getByLabelText(/stream/i)
  if (!streamToggle.checked) {
    await userEvent.click(streamToggle) // check
  }

  const input = screen.getByPlaceholderText(/type a message/i)
  await userEvent.type(input, 'hi')
  await userEvent.click(screen.getByRole('button', { name: /send/i }))

  // Expect concatenated assistant message "Hi!"
  await screen.findByText('Hi!', {}, { timeout: 2000 })
})

test('shows a friendly error when /api/chat returns error JSON', async () => {
  // Mock fetch: /api/chat returns {error:"..."}
  global.fetch = vi.fn(async (url, options) => {
    const u = String(url)
    if (u.endsWith('/api/chat')) {
      return jsonResponse({ error: 'Too Many Requests' }, { status: 429 })
    }
    if (u.endsWith('/api/chat/stream')) {
      return new Response('no stream', { status: 500 })
    }
    return new Response('not found', { status: 404 })
  })

  render(<ChatBot />)

  // Non-stream for determinism
  const streamToggle = screen.getByLabelText(/stream/i)
  if (streamToggle.checked) {
    await userEvent.click(streamToggle)
  }

  const input = screen.getByPlaceholderText(/type a message/i)
  await userEvent.type(input, 'trigger error')
  await userEvent.click(screen.getByRole('button', { name: /send/i }))

  // Your component prefixes error content with "Error: ..."
  await screen.findByText(/error:\s*too many requests/i)
})
