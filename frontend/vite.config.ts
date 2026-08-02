import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  build: {
    // M10 性能优化：vendor 分包（element-plus / echarts / 渲染链 / vue 核心），
    // 长期缓存更友好，初始加载可并行拉取。
    rollupOptions: {
      output: {
        manualChunks: {
          'vendor-vue': ['vue', 'vue-router', 'pinia'],
          'vendor-element': ['element-plus'],
          'vendor-echarts': ['echarts'],
          'vendor-markdown': ['katex', 'markdown-it', 'dompurify'],
        },
      },
    },
    chunkSizeWarningLimit: 1200,
  },
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    port: 5173,
    proxy: { '/api': { target: 'http://127.0.0.1:8321', changeOrigin: true } },
  },
})