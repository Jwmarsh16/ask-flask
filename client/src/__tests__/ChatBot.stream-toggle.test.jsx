// client/src/__tests__/ChatBot.stream-toggle.test.jsx
import React from 'react'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import ChatBot from '../components/ChatBot.jsx'

beforeEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

test('stream toggle persists in localStorage and across rerenders', async () => {
  const user = userEvent.setup()

  const first = render(React.createElement(ChatBot))

  const toggle1 = screen.getByLabelText(/stream/i)
  expect(toggle1).toBeChecked()

  await user.click(toggle1)
  expect(toggle1).not.toBeChecked()
  expect(localStorage.getItem('askFlaskStream')).toBe('false')

  first.unmount()

  render(React.createElement(ChatBot))

  const toggle2 = screen.getByLabelText(/stream/i)
  expect(toggle2).not.toBeChecked()
})
