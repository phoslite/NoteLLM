<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { listTasks } from '@/api/tasks'
import type { TaskItem } from '@/types'
import { TASK_SUBMITTED_EVENT } from '@/utils/task'

/** 全局任务中心（决策 35）：右下角浮窗，1s 轮询进行中任务，任务结束即停。 */

const items = ref<TaskItem[]>([])
const recents = ref<{ id: string; name: string; status: string; error?: string | null }[]>([])
const visible = ref(false)
let polling = false
let recentTimer: number | null = null

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms))
}

function pushRecent(t: TaskItem) {
  if (recents.value.some((r) => r.id === t.id)) return
  recents.value.unshift({ id: t.id, name: t.name, status: t.status, error: t.error })
  recents.value = recents.value.slice(0, 3)
  visible.value = true
  if (recentTimer !== null) clearTimeout(recentTimer)
  recentTimer = window.setTimeout(() => {
    recents.value = []
    if (items.value.length === 0) visible.value = false
  }, 4000)
}

async function pollOnce(): Promise<boolean> {
  try {
    const all = await listTasks()
    const active = all.filter((t) => t.status === 'queued' || t.status === 'running')
    items.value = active
    for (const t of all) {
      if (t.status === 'success' || t.status === 'failed') pushRecent(t)
    }
    return active.length > 0
  } catch {
    return false
  }
}

async function startPolling() {
  if (polling) return
  polling = true
  visible.value = true
  try {
    while (polling) {
      const more = await pollOnce()
      if (!more) break
      await sleep(1000)
    }
  } finally {
    polling = false
    if (items.value.length === 0 && recents.value.length === 0) visible.value = false
  }
}

function closePanel() {
  polling = false
  visible.value = false
  items.value = []
  recents.value = []
}

onMounted(() => {
  window.addEventListener(TASK_SUBMITTED_EVENT, startPolling)
  startPolling()
})
onBeforeUnmount(() => {
  window.removeEventListener(TASK_SUBMITTED_EVENT, startPolling)
  if (recentTimer !== null) clearTimeout(recentTimer)
})
</script>

<template>
  <transition name="task-fade">
    <div v-if="visible" class="task-center">
      <div class="task-head">
        <span>⚙️ 任务中心</span>
        <button class="task-close" title="关闭" @click="closePanel">✕</button>
      </div>
      <div v-for="t in items" :key="t.id" class="task-item">
        <div class="task-name">{{ t.name }}</div>
        <div class="task-bar">
          <div class="task-bar-fill" :style="{ width: `${t.progress ?? 0}%` }" />
        </div>
        <div class="task-stage">{{ t.stage || '处理中…' }}（{{ t.progress ?? 0 }}%）</div>
      </div>
      <div v-for="r in recents" :key="r.id" class="task-item" :class="r.status">
        <div class="task-name">
          {{ r.name }} · <span :class="r.status === 'success' ? 'ok' : 'bad'">{{ r.status === 'success' ? '完成' : '失败' }}</span>
        </div>
        <div v-if="r.status === 'failed' && r.error" class="task-error">{{ r.error }}</div>
      </div>
    </div>
  </transition>
</template>

<style scoped>
.task-center {
  position: fixed;
  right: 16px;
  bottom: 16px;
  width: 320px;
  max-height: 46vh;
  overflow: auto;
  background: var(--card-bg, #fff);
  border: 1px solid var(--border-color);
  border-radius: 10px;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.16);
  z-index: 3000;
  padding: 10px 12px;
  font-size: 13px;
}
.task-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  margin-bottom: 8px;
}
.task-close {
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-color);
  opacity: 0.65;
}
.task-close:hover { opacity: 1; }
.task-item { margin-bottom: 10px; }
.task-name { margin-bottom: 4px; word-break: break-all; }
.task-bar {
  height: 6px;
  border-radius: 3px;
  background: var(--border-color);
  overflow: hidden;
}
.task-bar-fill {
  height: 100%;
  border-radius: 3px;
  background: var(--primary-color, #409eff);
  transition: width 0.4s ease;
}
.task-stage { margin-top: 3px; color: #888; font-size: 12px; }
.task-error { margin-top: 3px; color: #f56c6c; font-size: 12px; word-break: break-all; }
.ok { color: #67c23a; font-weight: 600; }
.bad { color: #f56c6c; font-weight: 600; }
.task-fade-enter-active, .task-fade-leave-active { transition: opacity 0.25s, transform 0.25s; }
.task-fade-enter-from, .task-fade-leave-to { opacity: 0; transform: translateY(8px); }
</style>
