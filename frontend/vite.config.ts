import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

// All assets are bundled locally — no CDN at runtime (offline / intranet deployment).
// The frontend runs as its own process (no nginx, no Docker):
//   npm run dev    -> development server with hot reload (port 5173)
//   npm run serve  -> serves the production build in dist/ (port ELM_WEB_PORT, default 8088)
// Both forward /api to the backend (ELM_API_URL). Settings come from the repository-root .env.
export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, path.resolve(__dirname, '..'), ['ELM_', 'VITE_']), ...process.env }
  const api = env.ELM_API_URL || 'http://127.0.0.1:8000'
  const office = (env.ELM_ONLYOFFICE_PUBLIC_URL || 'http://localhost:8080').replace(/\/$/, '')
  // Optional intranet draw.io for the embedded diagram editor (frame only).
  const drawio = env.ELM_DRAWIO_URL ? ' ' + new URL(env.ELM_DRAWIO_URL).origin : ''
  const proxy = { '/api': { target: api, changeOrigin: false, xfwd: true } }
  const headers = {
    'X-Frame-Options': 'SAMEORIGIN',
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'same-origin',
    // OnlyOffice api.js and its frames come from the intranet Document Server.
    'Content-Security-Policy': `default-src 'self'; script-src 'self' ${office}; frame-src 'self' ${office}${drawio}; connect-src 'self' ${office}; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; worker-src 'self' blob:`,
  }
  return {
    plugins: [react()],
    envDir: path.resolve(__dirname, '..'),
    resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
    server: { host: env.ELM_WEB_HOST || 'localhost', port: 5173, proxy },
    preview: { host: env.ELM_WEB_HOST || '0.0.0.0', port: Number(env.ELM_WEB_PORT || 8088), strictPort: true, proxy, headers },
    build: {
      outDir: 'dist',
      sourcemap: false,
      chunkSizeWarningLimit: 2500,
      rollupOptions: {
        output: {
          manualChunks: {
            react: ['react', 'react-dom', 'react-router-dom'],
            mantine: ['@mantine/core', '@mantine/hooks', '@mantine/dates', '@mantine/notifications', '@mantine/modals', '@mantine/spotlight'],
            icons: ['@tabler/icons-react'],
            charts: ['recharts', '@mantine/charts'],
            flow: ['@xyflow/react'],
            pdf: ['pdfjs-dist'],
          },
        },
      },
    },
  }
})
