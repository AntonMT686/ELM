import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

// All assets are bundled locally — no CDN at runtime (offline / intranet deployment).
export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': path.resolve(__dirname, 'src') } },
  server: {
    port: 5173,
    proxy: { '/api': { target: process.env.ELM_API_URL || 'http://localhost:8000', changeOrigin: false } },
  },
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
})
