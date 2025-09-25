// client/src/__tests__/ChatBot.markdown.test.jsx
// Purpose: Verify Markdown rendering and Copy button UX with "Copied!" feedback.

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { vi } from 'vitest'
import ChatBot from '../components/ChatBot.jsx'

beforeEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

test('renders markdown and toggles Copy/Copied! on code block', async () => {
  vi.useFakeTimers() // ✅ control the 1200ms timeout in the copy handler

  // Seed LocalStorage so ChatBot loads an assistant message with a code fence
  const md = [
    'Here is code:',
    '',
    '```js',
    "console.log('hi')",
    '```'
  ].join('\n')

  localStorage.setItem(
    'askFlaskMessages',
    JSON.stringify([{ role: 'assistant', content: md, timestamp: '12:00' }])
  )

  // Spy on clipboard to verify it's called
  const writeSpy = vi.spyOn(navigator.clipboard, 'writeText').mockResolvedValue()

  render(<ChatBot />)

  // Markdown text appears
  expect(await screen.findByText('Here is code:')).toBeInTheDocument()

  // The code block's Copy button is present
  const copyBtn = await screen.findByRole('button', { name: /copy code/i })

  // Click triggers clipboard and sets data-copied="true"
  await userEvent.click(copyBtn)
  expect(writeSpy).toHaveBeenCalledTimes(1)
  await waitFor(() => {
    expect(copyBtn).toHaveAttribute('data-copied', 'true')
  })

  // After 1200ms, it flips back (handler sets "false")
  vi.runAllTimers()
  await waitFor(() => {
    expect(copyBtn).toHaveAttribute('data-copied', 'false')
  })

  vi.useRealTimers()
})
