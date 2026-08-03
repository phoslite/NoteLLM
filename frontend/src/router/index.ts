import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'home', component: () => import('@/views/HomeView.vue') },
    { path: '/reader/:bookId', name: 'reader', component: () => import('@/views/ReaderView.vue') },
    { path: '/rag', name: 'rag', component: () => import('@/views/RagView.vue') },
    { path: '/rag/:bookId', name: 'rag-detail', component: () => import('@/views/RagDetailView.vue') },
    { path: '/graph', name: 'graph', component: () => import('@/views/GraphView.vue') },
    { path: '/settings', name: 'settings', component: () => import('@/views/SettingsView.vue') },
    { path: '/profile', name: 'profile', component: () => import('@/views/ProfileView.vue') },
  ],
})

export default router