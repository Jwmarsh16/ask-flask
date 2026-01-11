// client/src/test/setup.jsx
// Purpose: One-time test setup (jest-dom matchers, shims, and clipboard mock).

import '@testing-library/jest-dom/vitest'
import { vi } from 'vitest' // CHANGED: use vi.fn() so clipboard is spy-able/deterministic in jsdom

// Stub matchMedia for future components that might query it
if (typeof window !== 'undefined' && !window.matchMedia) {
  window.matchMedia = () => ({
    matches: false,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })
}

// ✅ CHANGED: Always install a configurable clipboard mock for jsdom reliability
if (typeof navigator !== 'undefined') {
  const clipboardMock = {
    writeText: vi.fn().mockResolvedValue(undefined), // CHANGED: stable default; tests can overwrite
  }

  try {
    Object.defineProperty(navigator, 'clipboard', {
      value: clipboardMock,
      configurable: true, // CHANGED: allow per-test redefine/patching
      writable: true, // CHANGED: allow per-test assignment (navigator.clipboard = ...)
    })
  } catch {
    // CHANGED: fallback if clipboard is non-configurable in this env
    navigator.clipboard = clipboardMock
  }
}
