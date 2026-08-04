<script setup lang="ts">
import { useRoute } from 'vue-router'
import TaskCenter from '@/components/TaskCenter.vue'
const route = useRoute()
</script>

<template>
  <div class="app-shell">
    <header class="app-header">
      <span class="app-title">📚 读书阅读助手</span>
      <nav class="app-nav">
        <router-link to="/">书架</router-link>
        <router-link to="/rag">资料</router-link>
        <router-link to="/graph">谱系图</router-link>
        <router-link to="/profile">画像</router-link>
        <router-link to="/settings">设置</router-link>
      </nav>
    </header>
    <main class="app-main">
      <router-view :key="String(route.fullPath)" />
    </main>
    <TaskCenter />
  </div>
</template>

<style scoped>
.app-shell { display: flex; flex-direction: column; height: 100%; min-height: 100vh; min-height: 100dvh; }
.app-header { display: flex; align-items: center; gap: 24px; padding: 0 20px; height: 52px; border-bottom: 1px solid var(--border-color); flex: none; }
.app-title { font-weight: 700; }
.app-nav { display: flex; gap: 16px; }
.app-nav a { color: var(--text-color); text-decoration: none; }
.app-nav a.router-link-active { color: var(--primary-color); font-weight: 600; }
.app-main { flex: 1; min-height: 0; }
</style>