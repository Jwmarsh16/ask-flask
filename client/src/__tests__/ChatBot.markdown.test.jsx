// client/src/__tests__/ChatBot.markdown.test.jsx
import React from 'react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react' // CHANGED: use fireEvent for deterministic clicks in jsdom
import Prism from 'prismjs'

import ChatBot from '../components/ChatBot'

describe('ChatBot markdown', () => {
  let writeTextMock // CHANGED: keep direct ref to the exact mock function ChatBot will call

  beforeEach(() => {
    vi.spyOn(Prism, 'highlightAllUnder').mockImplementation(() => {}) // CHANGED: no-op Prism in tests

    // ✅ CHANGED: hard-set clipboard in the most jsdom-reliable way
    writeTextMock = vi.fn().mockResolvedValue(undefined) // CHANGED: deterministic clipboard writer
    const clipboardMock = { writeText: writeTextMock } // CHANGED: stable clipboard object

    try {
      Object.defineProperty(navigator, 'clipboard', {
        value: clipboardMock,
        configurable: true, // CHANGED: allow redefinition between tests
      })
    } catch {
      // CHANGED: fallback if clipboard is non-configurable in this env
      if (!navigator.clipboard) {
        navigator.clipboard = clipboardMock // CHANGED: last-resort assignment
      } else {
        navigator.clipboard.writeText = writeTextMock // CHANGED: patch existing clipboard
      }
    }

    localStorage.setItem(
      'askFlaskMessages',
      JSON.stringify([
        {
          role: 'assistant',
          content: "Here is some code:\n\n```js\nconsole.log('hello')\n```",
          timestamp: '00:00',
        },
      ])
    )
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
    localStorage.clear()
  })

  test(
    'renders markdown and toggles Copy/Copied! on code block',
    async () => {
      render(<ChatBot />)

      expect(screen.getByText(/here is some code/i)).toBeInTheDocument()

      // CHANGED: Prism tokenizes, so check textContent instead of getByText
      const codeEl = document.querySelector('code.language-js') || document.querySelector('code')
      expect(codeEl).toBeTruthy()
      expect(codeEl).toHaveTextContent("console.log('hello')") // CHANGED: lint-friendly matcher

      const copyBtn = screen.getByRole('button', { name: /copy code/i })
      expect(copyBtn).toBeInTheDocument()

      fireEvent.click(copyBtn) // CHANGED: fireEvent is more reliable than userEvent for this invalid <pre><div> nesting in jsdom

      // ✅ CHANGED: attribute is set only after clipboard write resolves, so wait for it
      await waitFor(() => {
        expect(writeTextMock).toHaveBeenCalledTimes(1) // CHANGED: deterministic call assertion
      })
      expect(writeTextMock).toHaveBeenCalledWith(expect.stringContaining("console.log('hello')")) // CHANGED

      await waitFor(() => {
        expect(copyBtn).toHaveAttribute('data-copied', 'true')
      })

      await waitFor(
        () => {
          expect(copyBtn).toHaveAttribute('data-copied', 'false')
        },
        { timeout: 2500 }
      )
    },
    10000
  )
})
