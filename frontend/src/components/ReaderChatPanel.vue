<script setup lang="ts">
import { nextTick, ref } from 'vue'
import type { UiChatMsg } from '@/composables/useReaderAi'
import MdRender from '@/components/MdRender.vue'

const props = defineProps<{
  messages: UiChatMsg[]
  streaming: boolean
  streamError: string
  contextTitle: string
  /** 会话模式：''=默认对话；解读/概论/思考逻辑=能力模式分池（决策 30）。 */
  chatMode: string
  /** 右侧折叠收起。 */
  collapsed: boolean
  /** 折叠期间新增的 AI 回复数。 */
  unread: number
}>()

/** 能力芯片：默认仅切池；解读/概论/思考逻辑切池并一键生成；脑图打开导图。 */
const MODE_CHIPS = [
  { value: '', label: '💬 默认' },
  { value: '解读', label: '📖 解读' },
  { value: '概论', label: '📄 概论' },
  { value: '思考逻辑', label: '🧩 思考逻辑' },
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
  (e: 'toggle-collapse'): void
}>()

function onChip(value: string) {
  if (value === '') {
    if (props.chatMode !== '') emit('mode-change', '')
    return
  }
  emit('preset', value)
}
</script>

<template>
  <aside v-if="!collapsed" class="ai-panel">
    <div class="ai-header">
      <h3 class="panel-title">AI 助手</h3>
      <button type="button" class="mini-icon" title="折叠到右侧" @click="emit('toggle-collapse')">➤</button>
    </div>
    <div class="ai-chips">
      <button
        v-for="m in MODE_CHIPS"
        :key="m.value"
        type="button"
        class="chip"
        :class="{ active: chatMode === m.value }"
        :disabled="streaming"
        @click="onChip(m.value)"
      >{{ m.label }}</button>
      <span class="chip-sep" aria-hidden="true"></span>
      <button type="button" class="chip chip-mind" :disabled="streaming" @click="emit('preset', '脑图')">🧠 脑图</button>
    </div>
    <div ref="chatBodyEl" class="chat-body">
      <div v-if="!messages.length" class="chat-empty">
        基于当前章节问答：点上方能力按钮一键生成，或输入问题回车发送。<br />回复支持 Markdown / LaTeX，引用出处自动标注。
      </div>
      <div
        v-for="m in messages"
        :key="m.id + m.role"
        class="chat-msg"
        :class="[m.role, { streaming: m.local }]"
      >
        <div class="chat-msg-head">
          <div class="chat-role">{{ m.role === 'user' ? '我' : 'AI' }}</div>
          <span v-if="m.cached" class="chat-cached" title="命中 LLM 结果缓存，未重复调用大模型">已缓存</span>
          <button v-if="m.content && !m.local" type="button" class="chat-copy" title="复制内容" @click="emit('copy', m.content)">复制</button>
        </div>
        <MdRender class="chat-content" :source="m.content || (m.local ? '思考中…' : '')" />
        <details v-if="m.thinking" class="chat-thinking">
          <summary class="chat-thinking-summary">🧠 思考过程（{{ m.thinking.length }} 字）</summary>
          <div class="chat-thinking-body">{{ m.thinking }}</div>
        </details>
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
        placeholder="输入问题…（Enter 发送）"
        @keydown.enter.exact.prevent="emit('send')"
      ></textarea>
      <el-button v-if="streaming" size="small" @click="emit('abort')">停止</el-button>
      <el-button v-else type="primary" size="small" :disabled="!input.trim()" @click="emit('send')">发送</el-button>
    </div>
  </aside>
  <button
    v-else
    type="button"
    class="ai-collapsed"
    :title="unread ? `展开 AI 助手（${unread} 条新回复）` : '展开 AI 助手'"
    @click="emit('toggle-collapse')"
  >
    <span class="ai-collapsed-icon">🤖</span>
    <span class="ai-collapsed-label">AI 助手</span>
    <span v-if="streaming" class="ai-live-dot" title="AI 正在回复"></span>
    <span v-if="unread" class="ai-unread">{{ unread > 99 ? '99+' : unread }}</span>
    <span class="ai-collapsed-arrow">◀</span>
  </button>
</template>

<style scoped>
.ai-panel {
  box-sizing: border-box;
  width: 30%;
  min-width: 320px;
  border-left: 1px solid var(--border-color);
  padding: 10px 12px 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.ai-header { flex: none; display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.panel-title { margin: 0; font-size: 13px; color: var(--text-color); font-weight: 600; letter-spacing: 0.5px; }
.mini-icon {
  border: 1px solid transparent; background: transparent; color: var(--text-secondary);
  width: 24px; height: 24px; border-radius: 6px; cursor: pointer; font-size: 12px; line-height: 1;
}
.mini-icon:hover { border-color: var(--border-color); background: var(--panel-bg); color: var(--primary-color); }

.ai-chips { flex: none; display: flex; gap: 4px; flex-wrap: wrap; padding: 0 0 6px; border-bottom: 1px solid var(--border-color); }
.chip {
  border: 1px solid var(--border-color); background: transparent; color: var(--text-secondary);
  font-size: 13px; padding: 5px 10px; border-radius: 12px; cursor: pointer; white-space: nowrap;
  min-height: 24px; display: inline-flex; align-items: center;
}
.chip:hover:not(:disabled) { border-color: var(--primary-color); color: var(--primary-color); }
.chip.active { border-color: var(--primary-color); color: var(--primary-color); background: color-mix(in srgb, var(--primary-color) 10%, transparent); font-weight: 600; }
.chip:disabled { opacity: 0.5; cursor: not-allowed; }
.chip-sep { width: 1px; background: var(--border-color); margin: 3px 3px; }
.chip-mind { border-style: dashed; }

.chat-body { flex: 1; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; padding: 2px; }
.chat-empty { color: var(--text-secondary); font-size: 13px; line-height: 1.8; padding: 6px 2px; }
.chat-msg { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.chat-msg.user .chat-content { background: var(--primary-color); color: #fff; padding: 8px 10px; border-radius: 8px; white-space: pre-wrap; }
.chat-msg.assistant .chat-content { background: var(--panel-bg); padding: 8px 10px; border-radius: 8px; overflow-x: auto; min-width: 0; } /* 三审 Moderate-2：长 KaTeX 公式横向可滚动，不再被面板裁剪 */
.chat-content :deep(.katex) { display: inline-block; max-width: 100%; overflow-x: auto; } /* E2E 五轮 #1：聊天区 Markdown 列表内行内公式收缩为 inline-block 并内部滚动，ul/li 不再横向溢出 */
.chat-msg.streaming .chat-content::after { content: '▍'; animation: blink 1s step-start infinite; color: var(--primary-color); }
@keyframes blink { 50% { opacity: 0; } }
.chat-role { font-size: 13px; color: var(--text-secondary); font-weight: 600; }
.chat-thinking { margin: 2px 0; border: 1px solid var(--border-color); border-radius: 6px; background: color-mix(in srgb, var(--panel-bg) 60%, transparent); }
.chat-thinking-summary { cursor: pointer; font-size: 13px; color: var(--text-secondary); padding: 5px 10px; user-select: none; min-height: 24px; display: flex; align-items: center; }
.chat-thinking-summary:hover { color: var(--primary-color); }
.chat-thinking-body { max-height: 160px; overflow-y: auto; padding: 0 10px 8px; font-size: 13px; line-height: 1.7; color: var(--text-secondary); white-space: pre-wrap; word-break: break-word; }
.chat-citations { display: flex; gap: 4px; flex-wrap: wrap; }
.citation-chip { font-size: 11px; color: var(--primary-color); border: 1px solid var(--primary-color); border-radius: 10px; padding: 1px 8px; }
.chat-error { color: var(--status-err); font-size: 13px; padding: 4px 2px; }
.chat-msg-head { display: flex; align-items: center; justify-content: space-between; }
.chat-cached { font-size: 11px; color: var(--primary-color); border: 1px solid var(--primary-color); border-radius: 4px; padding: 0 6px; opacity: 0.85; }
.chat-copy { border: none; background: transparent; color: #909399; font-size: 13px; cursor: pointer; padding: 0 2px; min-height: 24px; display: inline-flex; align-items: center; } /* E2E 五轮 #2：复制按钮可点击高度 >= 24px */
.chat-copy:hover { color: var(--primary-color); }
.chat-toolbar { flex: none; display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.chat-context { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; color: var(--text-secondary); }
.ai-input-row { flex: none; display: flex; gap: 6px; align-items: flex-end; }
.ai-input {
  flex: 1; height: 64px; resize: none;
  border: 1px solid var(--border-color); border-radius: 6px; padding: 8px 10px;
  background: var(--panel-bg); color: var(--text-color); font-family: inherit; font-size: 13px;
}
.ai-input:focus { outline: none; border-color: var(--primary-color); }
.ai-input:disabled { opacity: 0.6; }

/* 折叠条（收起时占据右侧窄栏） */
.ai-collapsed {
  box-sizing: border-box; width: 46px; height: 100%; flex: none;
  border: none; border-left: 1px solid var(--border-color);
  background: var(--panel-bg); color: var(--text-secondary);
  display: flex; flex-direction: column; align-items: center; gap: 12px;
  padding: 14px 0 18px; cursor: pointer; position: relative;
}
.ai-collapsed:hover { color: var(--primary-color); border-left-color: var(--primary-color); }
.ai-collapsed-icon { font-size: 18px; line-height: 1; }
.ai-collapsed-label { writing-mode: vertical-rl; text-orientation: mixed; font-size: 13px; letter-spacing: 3px; }
.ai-collapsed-arrow { font-size: 11px; line-height: 1; margin-top: auto; }
.ai-live-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--status-ok); animation: livePulse 1.2s ease-in-out infinite; }
@keyframes livePulse { 50% { opacity: 0.3; } }
.ai-unread {
  position: absolute; top: 8px; right: 3px;
  min-width: 16px; height: 16px; padding: 0 4px; border-radius: 8px;
  background: var(--status-err); color: #fff; font-size: 11px; line-height: 16px; text-align: center;
}
</style>
