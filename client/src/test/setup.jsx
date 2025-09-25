// client/src/test/setup.jsx
// Purpose: One-time test setup (jest-dom matchers, shims, and clipboard mock).

import '@testing-library/jest-dom/vitest'

// Stub matchMedia for future components that might query it
if (typeof window !== 'undefined' && !window.matchMedia) {
  window.matchMedia = () => ({
    matches: false,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false
  })
}

// ✅ ADDED: Robust clipboard mock so the Copy button test is deterministic
if (typeof navigator !== 'undefined' && !navigator.clipboard) {
  // minimal Promise-based mock consistent with the spec surface we use
  navigator.clipboard = {
    writeText: async () => {}
  }
}
