import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    // Three.js powers the lazy-loaded 3D dice roller. Keep Vite's raw-size
    // warning aligned with the stricter gzip/raw bundle budget script.
    chunkSizeWarningLimit: 620,
  },
})
