<template>
  <div class="doodle-toolbar" @mousedown.stop>
    <button
      v-for="t in tools"
      :key="t.key"
      type="button"
      class="mini-btn"
      :class="{ active: modelValue === t.key }"
      @click="emit('update:modelValue', t.key)"
    >
      {{ t.label }}
    </button>
    <span class="sep" />
    <label class="ctl">
      颜色
      <input v-model="color" type="color" class="color-input" />
    </label>
    <label class="ctl">
      线宽
      <input v-model.number="lineWidth" type="range" min="1" max="12" step="1" class="range-input" />
      <span class="val">{{ lineWidth }}</span>
    </label>
    <span class="sep" />
    <button type="button" class="mini-btn" :disabled="!canUndo" @click="undo">↩ 撤销</button>
    <button type="button" class="mini-btn danger" @click="clearAll">🗑 清除本页</button>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'

type DoodleTool = 'pen' | 'highlight' | 'eraser' | 'text'

const props = defineProps<{
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
  { key: 'pen', label: '✏ 笔刷' },
  { key: 'highlight', label: '🖍 高亮' },
  { key: 'eraser', label: '🧽 橡皮' },
  { key: 'text', label: '🔤 文本' },
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
  gap: 6px;
  flex-wrap: wrap;
  padding: 4px 8px;
  border: 1px solid var(--border-color, #dcdfe6);
  border-radius: 8px;
  background: #fff;
  font-size: 12px;
}
.mini-btn {
  border: 1px solid var(--border-color, #dcdfe6);
  background: #fff;
  color: var(--text-color, #303133);
  font-size: 12px;
  padding: 3px 6px;
  border-radius: 4px;
  cursor: pointer;
  white-space: nowrap;
}
.mini-btn:hover { border-color: var(--primary-color, #409eff); color: var(--primary-color, #409eff); }
.mini-btn.active { border-color: var(--primary-color, #409eff); color: var(--primary-color, #409eff); background: rgba(64, 158, 255, 0.08); }
.mini-btn.danger:hover { border-color: #f56c6c; color: #f56c6c; }
.mini-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.sep { width: 1px; height: 18px; background: var(--border-color, #dcdfe6); }
.ctl { display: inline-flex; align-items: center; gap: 4px; color: var(--text-secondary, #909399); }
.color-input { width: 26px; height: 20px; padding: 0; border: none; background: none; cursor: pointer; }
.range-input { width: 56px; }
.val { min-width: 14px; text-align: center; }
</style>
