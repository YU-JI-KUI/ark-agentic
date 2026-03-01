import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In production (npm run build), base is /studio/ to match FastAPI mount path.
// In development (npm run dev), base is / so the dev server works normally.
const isProd = process.env.NODE_ENV === 'production'

export default defineConfig({
  plugins: [react()],
  base: isProd ? '/studio/' : '/',
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
