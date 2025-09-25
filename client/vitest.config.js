// client/vitest.config.js
// Purpose: Vitest config with jsdom, setup file, CSS imports, and coverage gates.

import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.jsx'],
    css: true,
    globals: true,
    coverage: {
      reporter: ['text', 'html', 'json'],        // ✅ ADDED: useful CI & local reporters
      all: true,                                  // ✅ ADDED: include files without direct tests
      include: ['src/**/*.{js,jsx}'],             // ✅ ADDED: scope to app source
      exclude: [
        'src/**/__tests__/**',
        'src/test/**'
      ],
      thresholds: {                               // ✅ ADDED: quality bar per roadmap (>=80%)
        lines: 80,
        functions: 80,
        branches: 70,
        statements: 80
      }
    }
  }
})
