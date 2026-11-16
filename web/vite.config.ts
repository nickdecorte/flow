import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The build output is the page `app/server.py` serves: `app/static/index.html` plus
// `app/static/assets/*`. `emptyOutDir` keeps that folder free of leftovers.
export default defineConfig({
  base: '/',
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
  build: {
    outDir: '../app/static',
    emptyOutDir: true,
  },
})
