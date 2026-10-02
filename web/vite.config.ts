import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { readFileSync, existsSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))

// Wony picks its port at startup and writes it here (helpers/server_address.py).
function backendPort(): number {
  const runtimeFile = resolve(__dirname, '../.wony_server')
  if (!existsSync(runtimeFile)) return 8000
  const port = parseInt(readFileSync(runtimeFile, 'utf-8').trim(), 10)
  return Number.isFinite(port) ? port : 8000
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': {
        target: `http://127.0.0.1:${backendPort()}`,
        changeOrigin: true,
        ws: true,
        // Wony's backend only accepts same-origin requests (helpers/server_address.py)
        // and has no notion of the Vite dev server, so the proxy — not the
        // backend — is what makes the dev page's requests look same-origin.
        rewriteWsOrigin: true,
        configure: (proxy, options) => {
          proxy.on('proxyReq', (proxyReq) => {
            if (proxyReq.getHeader('origin')) {
              proxyReq.setHeader('origin', options.target as string)
            }
          })
        },
      },
    },
  },
})
