import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Proxying /api keeps the browser's view same-origin (localhost:5173),
    // so the refresh-token cookie (SameSite=Strict) and CORS both behave
    // exactly as they will once Flask and the built frontend are served
    // from the same origin in production, without any dev-only CORS carveouts.
    proxy: {
      '/api': {
        target: 'http://localhost:5002',
        changeOrigin: true,
      },
    },
  },
})
