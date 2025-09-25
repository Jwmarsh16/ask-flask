// client/src/__tests__/ChatBot.stream-toggle.test.jsx
// ✅ NEW: ensures the Stream toggle persists across reloads via localStorage.

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import ChatBot from '../components/ChatBot.jsx'

beforeEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

test('stream toggle persists in localStorage and across rerenders', async () => {
  render(<ChatBot />)

  // Default is true (checked)
  const toggle = screen.getByLabelText(/stream/i)
  expect(toggle).toBeChecked()

  // Turn OFF streaming
  await userEvent.click(toggle)
  expect(toggle).not.toBeChecked()
  expect(localStorage.getItem('askFlaskStream')).toBe('false')

  // Re-render fresh instance (simulate reload)
  localStorage.setItem('askFlaskStream', 'false')
  render(<ChatBot />)

  // Should remain unchecked based on stored value
  const toggle2 = screen.getByLabelText(/stream/i)
  expect(toggle2).not.toBeChecked()
})
