import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [tailwindcss(), svelte()],
  server: {
    proxy: {
      '/api': 'http://localhost:8888',
      // Proxy media files to Python server
      '^/.*\\.(mp4|mkv|avi|mov|webm|json|wav|mp3)$': {
        target: 'http://localhost:8888',
        changeOrigin: true,
      },
    }
  },
  build: {
    outDir: '../dist',
    emptyOutDir: false,
  }
})
