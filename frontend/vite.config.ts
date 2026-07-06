import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ command, mode }) => {
  // Fail the BUILD, not the visitor's page load, when the API origin is
  // missing: a production bundle without VITE_API_URL used to silently fall
  // back to http://localhost:8000 — i.e., send requests (and BYOK keys) to
  // whatever runs on the visitor's own machine.
  const env = loadEnv(mode, process.cwd(), '')
  if (command === 'build' && mode === 'production' && !env.VITE_API_URL) {
    throw new Error(
      'VITE_API_URL must be set for production builds (the deployed API origin).'
    )
  }

  return {
    plugins: [react()],
    server: {
      port: 3000,
      proxy: {
        '/api': {
          target: 'http://localhost:8000',
          changeOrigin: true,
        },
        '/health': {
          target: 'http://localhost:8000',
          changeOrigin: true,
        },
      },
    },
  }
})
