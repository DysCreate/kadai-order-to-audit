import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'Kadai',
        short_name: 'Kadai',
        theme_color: '#1e40af',
        icons: [{ src: '/favicon.ico', sizes: '64x64', type: 'image/x-icon' }]
      }
    })
  ],
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true }
    }
  }
})
