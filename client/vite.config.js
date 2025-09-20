// client/vite.config.js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Vite config for React app under /client
// - base:'/' works for Render (static assets resolve correctly)
// - server.proxy is DEV-ONLY; in production the app is served by Flask and hits
//   the API at the same origin (no proxy or CORS required).
export default defineConfig({
  base: '/',                 // ensure correct asset paths when built
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:5555', // Flask dev server
        changeOrigin: true,
        // rewrite: (path) => path.replace(/^\/api/, ''), // keep commented
      },
    },
  },
})
