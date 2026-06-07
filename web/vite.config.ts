import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { readFileSync, existsSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))

function readServerConfig(): { host: string; port: number } {
  const defaults = { host: '127.0.0.1', port: 8000 }
  const configPath = resolve(__dirname, '../config.yaml')
  if (!existsSync(configPath)) return defaults
  try {
    const content = readFileSync(configPath, 'utf-8')
    const blockMatch = content.match(/^server:\s*\n((?:[ \t]+[^\n]*\n?)*)/m)
    if (!blockMatch) return defaults
    const block = blockMatch[1]
    const host = block.match(/host:\s*["']?([^"'\s#\n]+)["']?/)?.[1] ?? defaults.host
    const portStr = block.match(/port:\s*(\d+)/)?.[1]
    return { host, port: portStr ? parseInt(portStr, 10) : defaults.port }
  } catch {
    return defaults
  }
}

const { host, port } = readServerConfig()

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': {
        target: `http://${host}:${port}`,
        changeOrigin: true,
      },
    },
  },
})
