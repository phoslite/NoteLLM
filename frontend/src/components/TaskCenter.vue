<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { listTasks } from '@/api/tasks'
import type { TaskItem } from '@/types'
import { TASK_SUBMITTED_EVENT } from '@/utils/task'

/** 全局任务中心（决策 35 + 性能优化 §8 任务中心优化）：
 * - 类型图标（text/vision/render/generic）与类型标签；
 * - 进行中：进度条 + 百分比 + 阶段文案；成功/失败彩色标签；
 * - 最近 3 条已完成横条，失败项点击展开错误详情；hover 显示创建时间；
 * - 面板可折叠/展开，右上角可清空最近记录（仅前端隐藏）。 */

const TYPE_ICON: Record<string, string> = { text: '📝', vision: '👁', render: '🖼', generic: '⚙️' }
const TYPE_LABEL: Record<string, string> = { text: '文本', vision: '视觉', render: '渲染', generic: '通用' }

const items = ref<TaskItem[]>([])
const recents = ref<TaskItem[]>([])
const visible = ref(false)
const collapsed = ref(false)
const expandedError = ref<string | null>(null)
let polling = false
let recentTimer: number | null = null

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms))
}

function typeIcon(t: TaskItem) {
  return TYPE_ICON[t.type] ?? '⚙️'
}

function typeLabel(t: TaskItem) {
  return TYPE_LABEL[t.type] ?? (t.type || '通用')
}

function fmtTime(iso: string | null) {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString('zh-CN', { hour12: false })
}

function pushRecent(t: TaskItem) {
  if (recents.value.some((r) => r.id === t.id)) return
  recents.value.unshift(t)
  recents.value = recents.value.slice(0, 3)
  visible.value = true
  if (recentTimer !== null) clearTimeout(recentTimer)
  recentTimer = window.setTimeout(() => {
    recents.value = []
    if (items.value.length === 0) visible.value = false
  }, 6000)
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
  expandedError.value = null
}

function clearRecents() {
  recents.value = []
  if (items.value.length === 0) visible.value = false
}

function toggleError(t: TaskItem) {
  if (t.status !== 'failed') return
  expandedError.value = expandedError.value === t.id ? null : t.id
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
        <span class="task-title">
          ⚙️ 任务中心
          <span v-if="items.length" class="task-count" :title="`${items.length} 个进行中任务`">{{ items.length }}</span>
        </span>
        <div class="task-head-actions">
          <button class="task-ghost" :title="collapsed ? '展开面板' : '折叠面板'" @click="collapsed = !collapsed">
            {{ collapsed ? '▸' : '▾' }}
          </button>
          <button class="task-close" title="关闭" @click="closePanel">✕</button>
        </div>
      </div>
      <div v-show="!collapsed" class="task-body">
        <div v-if="!items.length && !recents.length" class="task-empty">暂无任务</div>

        <div v-for="t in items" :key="t.id" class="task-item running">
          <div class="task-name">
            <span class="task-type">{{ typeIcon(t) }} {{ typeLabel(t) }}</span>
            <span class="task-title-text">{{ t.name }}</span>
            <span v-if="t.related_id" class="task-related" title="关联书籍 ID">#{{ t.related_id }}</span>
          </div>
          <div class="task-bar">
            <div class="task-bar-fill" :style="{ width: `${t.progress ?? 0}%` }" />
          </div>
          <div class="task-stage">{{ t.stage || '处理中…' }}（{{ t.progress ?? 0 }}%）</div>
        </div>

        <div v-if="recents.length" class="task-recents">
          <div class="task-recents-head">
            <span>最近完成</span>
            <button class="task-ghost" title="清空最近记录（仅隐藏显示）" @click="clearRecents">清空</button>
          </div>
          <div
            v-for="r in recents"
            :key="r.id"
            class="task-item recent"
            :class="r.status"
            :title="`创建：${fmtTime(r.created_at)}`"
            @click="toggleError(r)"
          >
            <div class="task-name">
              <span class="task-type">{{ typeIcon(r) }} {{ typeLabel(r) }}</span>
              <span class="task-status" :class="r.status === 'success' ? 'ok' : 'bad'">
                {{ r.status === 'success' ? '成功' : '失败' }}
              </span>
              <span class="task-title-text">{{ r.name }}</span>
              <span v-if="r.related_id" class="task-related" title="关联书籍 ID">#{{ r.related_id }}</span>
            </div>
            <div v-if="r.status === 'failed'" class="task-error-toggle">
              {{ expandedError === r.id ? '▲ 收起详情' : '▼ 点击查看详情' }}
            </div>
            <div v-if="expandedError === r.id && r.error" class="task-error">{{ r.error }}</div>
          </div>
        </div>
      </div>
    </div>
  </transition>
</template>

<style scoped>
.task-center {
  position: fixed;
  right: 16px;
  bottom: 16px;
  width: 340px;
  max-height: 52vh;
  display: flex;
  flex-direction: column;
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
  flex: none;
}
.task-title { display: flex; align-items: center; gap: 6px; }
.task-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: var(--primary-color, #409eff);
  color: #fff;
  font-size: 11px;
  font-weight: 600;
}
.task-head-actions { display: flex; gap: 2px; }
.task-ghost, .task-close {
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-color);
  opacity: 0.65;
  padding: 2px 6px;
  border-radius: 4px;
}
.task-ghost:hover, .task-close:hover { opacity: 1; background: var(--border-color); }
.task-body { overflow: auto; }
.task-empty { color: var(--text-secondary); text-align: center; padding: 14px 0; }
.task-item { margin-bottom: 10px; }
.task-item.running { animation: task-pulse 1.6s ease-in-out infinite; }
.task-name { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; word-break: break-all; }
.task-title-text { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-type {
  flex: none;
  font-size: 11px;
  color: var(--text-secondary);
  background: var(--bg-color, #f5f7fa);
  border-radius: 4px;
  padding: 1px 6px;
  white-space: nowrap;
}
.task-related { flex: none; font-size: 11px; color: #909399; }
.task-status { flex: none; font-size: 11px; border-radius: 4px; padding: 1px 6px; font-weight: 600; white-space: nowrap; }
.task-status.ok { color: #67c23a; background: rgba(103, 194, 58, 0.12); }
.task-status.bad { color: #f56c6c; background: rgba(245, 108, 108, 0.12); }
.task-bar {
  height: 6px;
  border-radius: 3px;
  background: var(--border-color);
  overflow: hidden;
}
.task-bar-fill {
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(90deg, var(--primary-color, #409eff), #79bbff);
  transition: width 0.4s ease;
}
.task-stage { margin-top: 3px; color: #888; font-size: 12px; }
.task-recents { border-top: 1px dashed var(--border-color); padding-top: 6px; }
.task-recents-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 12px;
  color: var(--text-secondary);
  margin-bottom: 6px;
}
.task-item.recent { cursor: default; }
.task-item.recent.failed { cursor: pointer; }
.task-error-toggle { margin-top: 3px; font-size: 11px; color: #e6a23c; }
.task-error { margin-top: 3px; color: #f56c6c; font-size: 12px; word-break: break-all; white-space: pre-wrap; }
.ok { color: #67c23a; font-weight: 600; }
.bad { color: #f56c6c; font-weight: 600; }
@keyframes task-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.82; }
}
.task-fade-enter-active, .task-fade-leave-active { transition: opacity 0.25s, transform 0.25s; }
.task-fade-enter-from, .task-fade-leave-to { opacity: 0; transform: translateY(8px); }
</style>