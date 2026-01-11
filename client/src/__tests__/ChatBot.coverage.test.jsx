// client/src/__tests__/ChatBot.coverage.test.jsx
import React from 'react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import Prism from 'prismjs'

import ChatBot from '../components/ChatBot'

function makeResponse(status, body, headers = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: {
      get: (key) => headers[key] ?? null, // CHANGED: match Response.headers.get API
    },
    json: async () => body,
  }
}

describe('ChatBot coverage', () => {
  beforeEach(() => {
    vi.spyOn(Prism, 'highlightAllUnder').mockImplementation(() => {}) // CHANGED: keep Prism deterministic
    localStorage.clear()

    // CHANGED: provide scrollIntoView so we cover the guarded call path
    HTMLElement.prototype.scrollIntoView = vi.fn() // CHANGED: cover smooth-scroll branch
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    localStorage.clear()
    delete global.fetch
  })

  test('loads server history when sessionId exists', async () => {
    global.fetch = vi.fn().mockResolvedValueOnce(
      makeResponse(200, {
        messages: [
          {
            role: 'assistant',
            content: 'Hello from server',
            created_at: '2025-01-01T12:34:56Z', // CHANGED: valid ISO path
          },
          {
            role: 'user',
            content: 'Hi there',
            created_at: 'not-a-date', // CHANGED: invalid ISO path
          },
          {
            role: 'assistant',
            content: 'No timestamp',
            created_at: null, // CHANGED: missing timestamp path
          },
        ],
      })
    )

    render(<ChatBot sessionId="sess_123" />)

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledTimes(1) // CHANGED: ensure session history fetch ran
    })

    expect(screen.getByText('Hello from server')).toBeInTheDocument()
    expect(screen.getByText('Hi there')).toBeInTheDocument()
    expect(screen.getByText('No timestamp')).toBeInTheDocument()

    // CHANGED: effect persists mapped messages back to localStorage
    expect(localStorage.getItem('askFlaskMessages')).toContain('Hello from server')
  })

  test('Clear Chat creates new session and notifies parent', async () => {
    localStorage.setItem(
      'askFlaskMessages',
      JSON.stringify([{ role: 'assistant', content: 'Old chat', timestamp: '00:00' }])
    )

    global.fetch = vi.fn().mockResolvedValueOnce(makeResponse(200, { id: 'sess_new' }))

    const onSelectSession = vi.fn()

    render(<ChatBot onSelectSession={onSelectSession} />)

    expect(screen.getByText('Old chat')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /clear chat/i })) // CHANGED: deterministic click

    await waitFor(() => {
      expect(onSelectSession).toHaveBeenCalledWith('sess_new') // CHANGED: success path calls callback
    })

    expect(localStorage.getItem('askFlaskMessages')).toBeNull() // CHANGED: cleared by handleClearChat()
  })

  test('non-stream error formatting covers 429 and 413', async () => {
    localStorage.setItem('askFlaskStream', 'false') // CHANGED: force non-stream path in tests

    global.fetch = vi
      .fn()
      .mockResolvedValueOnce(
        makeResponse(
          429,
          { request_id: 'req_429' },
          { 'X-RateLimit-Remaining': '4' } // CHANGED: cover rateRemaining header path
        )
      )
      .mockResolvedValueOnce(
        makeResponse(413, { request_id: 'req_413' }, { 'X-RateLimit-Remaining': '3' })
      )

    render(<ChatBot />)

    const input = screen.getByLabelText(/message input/i)
    const sendBtn = screen.getByRole('button', { name: /send message/i })

    fireEvent.change(input, { target: { value: 'hello' } }) // CHANGED: drive input without user-event
    fireEvent.click(sendBtn)

    expect(await screen.findByText(/too many requests/i)).toBeInTheDocument()
    expect(screen.getByText(/rate limit:\s*4\s*left/i)).toBeInTheDocument()

    fireEvent.change(input, { target: { value: 'second' } })
    fireEvent.click(sendBtn)

    expect(await screen.findByText(/message is too long/i)).toBeInTheDocument()
    expect(screen.getByText(/rate limit:\s*3\s*left/i)).toBeInTheDocument()
  })

  test('non-stream network error shows fallback message', async () => {
    localStorage.setItem('askFlaskStream', 'false') // CHANGED: force non-stream path

    global.fetch = vi.fn().mockRejectedValueOnce(new Error('boom')) // CHANGED: cover catch branch

    render(<ChatBot />)

    const input = screen.getByLabelText(/message input/i)
    const sendBtn = screen.getByRole('button', { name: /send message/i })

    fireEvent.change(input, { target: { value: 'test' } })
    fireEvent.click(sendBtn)

    expect(await screen.findByText(/network error/i)).toBeInTheDocument()
  })
})
