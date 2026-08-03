<script setup lang="ts">
import { nextTick, ref } from 'vue'
import type { UiChatMsg } from '@/composables/useReaderAi'
import MdRender from '@/components/MdRender.vue'

defineProps<{
  messages: UiChatMsg[]
  streaming: boolean
  streamError: string
  contextTitle: string
  /** 会话模式：''=默认对话；解读/概论/思考逻辑=能力模式分池（决策 30）。 */
  chatMode: string
}>()

const MODE_TABS = [
  { value: '', label: '默认' },
  { value: '解读', label: '解读' },
  { value: '概论', label: '概论' },
  { value: '思考逻辑', label: '思考逻辑' },
]

const chatBodyEl = ref<HTMLElement | null>(null)

/** 流式输出期间把聊天区滚到底部（由父级组合式函数在事件回调中调用）。 */
function scrollToBottom() {
  void nextTick(() => {
    if (chatBodyEl.value) chatBodyEl.value.scrollTop = chatBodyEl.value.scrollHeight
  })
}

defineExpose({ scrollToBottom })

const input = defineModel<string>('input', { required: true })

const emit = defineEmits<{
  (e: 'preset', kind: string): void
  (e: 'mode-change', mode: string): void
  (e: 'send'): void
  (e: 'abort'): void
  (e: 'clear'): void
  (e: 'copy', text: string): void
}>()
</script>

<template>
  <aside class="ai-panel">
    <h3 class="panel-title">AI 助手</h3>
    <div class="ai-modes">
      <button
        v-for="m in MODE_TABS"
        :key="m.value"
        type="button"
        class="mode-tab"
        :class="{ active: chatMode === m.value }"
        :disabled="streaming"
        @click="emit('mode-change', m.value)"
      >{{ m.label }}</button>
    </div>
    <div class="ai-presets">
      <button
        v-for="p in ['解读', '概论', '脑图', '思考逻辑']"
        :key="p"
        type="button"
        class="preset-btn"
        :disabled="streaming"
        @click="emit('preset', p)"
      >{{ p }}</button>
    </div>
    <div ref="chatBodyEl" class="chat-body">
      <div v-if="!messages.length" class="chat-empty">
        基于当前章节问答：输入问题，或点上方能力按钮。<br />回复支持 Markdown / LaTeX，引用出处自动标注。
      </div>
      <div
        v-for="m in messages"
        :key="m.id + m.role"
        class="chat-msg"
        :class="[m.role, { streaming: m.local }]"
      >
        <div class="chat-msg-head">
          <div class="chat-role">{{ m.role === 'user' ? '我' : 'AI' }}</div>
          <button v-if="m.content && !m.local" type="button" class="chat-copy" title="复制内容" @click="emit('copy', m.content)">复制</button>
        </div>
        <MdRender class="chat-content" :source="m.content || (m.local ? '思考中…' : '')" />
        <div v-if="m.citations?.length" class="chat-citations">
          <span v-for="(c, i) in m.citations" :key="i" class="citation-chip">{{ c.para === '页' ? `第${c.chapter}页` : `第${c.chapter}章 第${c.para}段` }}</span>
        </div>
      </div>
      <div v-if="streamError" class="chat-error">{{ streamError }}</div>
    </div>
    <div class="chat-toolbar">
      <span class="chat-context" :title="contextTitle">{{ contextTitle }}</span>
      <el-button size="small" text :disabled="streaming" @click="emit('clear')">清空</el-button>
    </div>
    <div class="ai-input-row">
      <textarea
        v-model="input"
        class="ai-input"
        :disabled="streaming"
        placeholder="输入问题…（Markdown/LaTeX）"
        @keydown.enter.exact.prevent="emit('send')"
      ></textarea>
      <el-button v-if="streaming" size="small" @click="emit('abort')">停止</el-button>
      <el-button v-else type="primary" size="small" :disabled="!input.trim()" @click="emit('send')">发送</el-button>
    </div>
  </aside>
</template>

<style scoped>
.ai-panel {
  box-sizing: border-box;
  width: 30%;
  min-width: 320px;
  border-left: 1px solid var(--border-color);
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.panel-title { margin: 0 0 10px; font-size: 13px; color: var(--text-secondary); font-weight: 600; letter-spacing: 0.5px; }
.ai-modes { display: flex; gap: 4px; flex-wrap: wrap; flex: none; padding-bottom: 2px; }
.mode-tab {
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-secondary);
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 10px;
  cursor: pointer;
}
.mode-tab:hover:not(:disabled) { color: var(--primary-color); }
.mode-tab.active { border-color: var(--primary-color); color: var(--primary-color); background: color-mix(in srgb, var(--primary-color) 10%, transparent); }
.mode-tab:disabled { opacity: 0.5; cursor: not-allowed; }
.ai-presets { display: flex; gap: 6px; flex-wrap: wrap; flex: none; }
.preset-btn {
  border: 1px solid var(--border-color);
  background: transparent;
  color: var(--text-color);
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 14px;
  cursor: pointer;
}
.preset-btn:hover:not(:disabled) { border-color: var(--primary-color); color: var(--primary-color); }
.preset-btn:disabled { opacity: 0.5; cursor: not-allowed; }

.chat-body { flex: 1; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; padding: 2px; }
.chat-empty { color: var(--text-secondary); font-size: 12px; line-height: 1.8; padding: 8px 2px; }
.chat-msg { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.chat-msg.user .chat-content { background: var(--primary-color); color: #fff; padding: 8px 10px; border-radius: 8px; white-space: pre-wrap; }
.chat-msg.assistant .chat-content { background: var(--panel-bg); padding: 8px 10px; border-radius: 8px; }
.chat-msg.streaming .chat-content::after { content: '▍'; animation: blink 1s step-start infinite; color: var(--primary-color); }
@keyframes blink { 50% { opacity: 0; } }
.chat-role { font-size: 11px; color: var(--text-secondary); font-weight: 600; }
.chat-citations { display: flex; gap: 4px; flex-wrap: wrap; }
.citation-chip { font-size: 11px; color: var(--primary-color); border: 1px solid var(--primary-color); border-radius: 10px; padding: 1px 8px; }
.chat-error { color: #f56c6c; font-size: 12px; padding: 4px 2px; }
.chat-msg-head { display: flex; align-items: center; justify-content: space-between; }
.chat-copy { border: none; background: transparent; color: #909399; font-size: 12px; cursor: pointer; padding: 0 2px; }
.chat-copy:hover { color: var(--primary-color); }
.chat-toolbar { flex: none; display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.chat-context { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; color: var(--text-secondary); }
.ai-input-row { flex: none; display: flex; gap: 8px; align-items: flex-end; }
.ai-input {
  flex: 1;
  height: 72px;
  resize: none;
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 10px;
  background: var(--panel-bg);
  color: var(--text-color);
  font-family: inherit;
}
</style>
