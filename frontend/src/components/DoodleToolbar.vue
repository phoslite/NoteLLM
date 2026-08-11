<template>
  <div class="doodle-toolbar" @mousedown.stop>
    <button
      v-for="t in tools"
      :key="t.key"
      type="button"
      class="mini-btn"
      :class="{ active: modelValue === t.key }"
      :title="t.key === 'pen' ? '✏ 笔刷' : t.key === 'highlight' ? '🖍 高亮' : t.key === 'eraser' ? '🧽 橡皮' : '🔤 文本'"
      @click="emit('update:modelValue', t.key)"
    >
      {{ t.label }}
    </button>
    <span class="sep" />
    <label class="ctl" title="颜色">
      <input v-model="color" type="color" class="color-input" />
    </label>
    <label class="ctl" title="线宽">
      <input v-model.number="lineWidth" type="range" min="1" max="12" step="1" class="range-input" />
      <span class="val">{{ lineWidth }}</span>
    </label>
    <span class="sep" />
    <button type="button" class="mini-btn" :disabled="!canUndo" title="撤销上一步" @click="undo">↩ 撤销</button>
    <button type="button" class="mini-btn danger" title="清除本页全部涂鸦" @click="clearAll">🗑 清除</button>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'

type DoodleTool = 'pen' | 'highlight' | 'eraser' | 'text'

defineProps<{
  modelValue: DoodleTool
  canUndo: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: DoodleTool): void
  (e: 'undo'): void
  (e: 'clear'): void
  (e: 'update:color', v: string): void
  (e: 'update:lineWidth', v: number): void
}>()

const tools: { key: DoodleTool; label: string }[] = [
  { key: 'pen', label: '笔刷' },
  { key: 'highlight', label: '高亮' },
  { key: 'eraser', label: '橡皮' },
  { key: 'text', label: '文本' },
]

const color = ref('#e74c3c')
const lineWidth = ref(3)

watch(color, (v) => emit('update:color', v))
watch(lineWidth, (v) => emit('update:lineWidth', v))

function undo() {
  emit('undo')
}

async function clearAll() {
  try {
    await ElMessageBox.confirm('清除本页全部涂鸦标注？', '提示', { type: 'warning' })
    emit('clear')
  } catch {
    /* 取消 */
  }
}
</script>

<style scoped>
.doodle-toolbar {
  display: flex;
  align-items: center;
  gap: 3px;
  flex-wrap: nowrap;
  overflow-x: auto;
  scrollbar-width: none;
  padding: 2px 6px;
  border: 1px solid var(--border-color, #dcdfe6);
  border-radius: 8px;
  background: #fff;
  font-size: 13px;
}
.mini-btn {
  border: 1px solid var(--border-color, #dcdfe6);
  background: #fff;
  color: var(--text-color, #303133);
  font-size: 13px;
  padding: 3px 6px;
  border-radius: 4px;
  cursor: pointer;
  white-space: nowrap;
  min-height: 24px;
}
.mini-btn:hover { border-color: var(--primary-color, #2f6fb0); color: var(--primary-color, #2f6fb0); }
.mini-btn.active { border-color: var(--primary-color, #2f6fb0); color: var(--primary-color, #2f6fb0); background: color-mix(in srgb, var(--primary-color) 8%, transparent); }
.mini-btn.danger:hover { border-color: var(--status-err, #e0382e); color: var(--status-err, #e0382e); }
.mini-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.sep { width: 1px; height: 12px; background: var(--border-color, #dcdfe6); }
.ctl { display: inline-flex; align-items: center; gap: 3px; color: var(--text-secondary, #909399); }
.color-input { width: 24px; height: 24px; padding: 0; border: none; background: none; cursor: pointer; } /* E2E 四轮 m7：色板点击目标 >= 24px */
.range-input { width: 36px; }
.val { min-width: 12px; text-align: center; }
.doodle-toolbar::-webkit-scrollbar { display: none; }
</style>
