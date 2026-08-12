<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import MdRender from '@/components/MdRender.vue'
import type { UiGlobalMsg } from '@/composables/useGlobalAi'

/** 决策 37：主页全局 AI 对话浮窗——阅读之外使用 Skill/RAG 资产辅助用户。 */
const props = defineProps<{
  messages: UiGlobalMsg[]
  streaming: boolean
  streamError: string
  /** 折叠收起（只保留右下角入口按钮）。 */
  collapsed: boolean
  /** 折叠期间新增的 AI 回复数。 */
  unread: number
}>()

const emit = defineEmits<{
  (e: 'send'): void
  (e: 'abort'): void
  (e: 'clear'): void
  (e: 'delete-session'): void
  (e: 'copy', text: string): void
  (e: 'toggle-collapse'): void
}>()

const input = defineModel<string>('input', { required: true })

const chatBodyEl = ref<HTMLElement | null>(null)

/** 流式输出期间把聊天区滚到底部（父级在消息变化时调用）。 */
/** Enter 发送（P1-1 v1.138）：中文输入法组词确认键（isComposing/keyCode 229）不触发发送。 */
function onEnterKey(e: KeyboardEvent) {
  if (e.isComposing || e.keyCode === 229) return
  emit('send')
}

function scrollToBottom() {
  void nextTick(() => {
    if (chatBodyEl.value) chatBodyEl.value.scrollTop = chatBodyEl.value.scrollHeight
  })
}

defineExpose({ scrollToBottom })

/** 新消息/流式增量时自动滚动到底部（P2-5：只追踪最后一条消息长度 + streaming 标志，
 *  避免全量 map+join 在中间消息变化时也触发滚动）。 */
watch(
  () => {
    const last = props.messages[props.messages.length - 1]
    const len = last ? last.content.length + (last.thinking?.length ?? 0) : 0
    return `${props.streaming}:${len}`
  },
  () => scrollToBottom(),
)
</script>

<template>
  <div v-if="!collapsed" class="global-ai-panel">
    <div class="global-ai-header">
      <h3 class="global-ai-title">💬 全局 AI 助手</h3>
      <span class="global-ai-sub">阅读之外：结合你的 Skill / RAG 知识库与画像问答</span>
      <button type="button" class="mini-icon" title="折叠" @click="emit('toggle-collapse')">➤</button>
    </div>
    <div ref="chatBodyEl" class="chat-body">
      <div v-if="!messages.length" class="chat-empty">
        不依赖任何正在阅读的书，AI 会结合知识库中的 Skill 技能与跨书 RAG 片段回答你——
        答疑、概念解释、跨书提问、思路梳理均可。<br />回复支持 Markdown / LaTeX，跨书引用自动标注出处。
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
      <span class="chat-context" title="会话说明">会话按 session_id 持久化，重开面板载入原历史；清空保留会话，删除会话换新会话</span>
      <span class="chat-toolbar-actions">
        <el-button size="small" text :disabled="streaming" @click="emit('clear')">清空</el-button>
        <el-button size="small" text type="danger" :disabled="streaming || !messages.length" @click="emit('delete-session')">删除会话</el-button>
      </span>
    </div>
    <div class="ai-input-row">
      <textarea
        v-model="input"
        class="ai-input"
        :disabled="streaming"
        placeholder="输入问题…（Enter 发送）"
        @keydown.enter.exact.prevent="onEnterKey"
      ></textarea>
      <el-button v-if="streaming" size="small" @click="emit('abort')">停止</el-button>
      <el-button v-else type="primary" size="small" :disabled="!input.trim()" @click="emit('send')">发送</el-button>
    </div>
  </div>
  <button
    v-else
    type="button"
    class="global-ai-fab"
    :title="unread ? `打开全局 AI 助手（${unread} 条新回复）` : '打开全局 AI 助手'"
    @click="emit('toggle-collapse')"
  >
    <span class="fab-icon">🤖</span>
    <span class="fab-label">AI</span>
    <span v-if="streaming" class="ai-live-dot" title="AI 正在回复"></span>
    <span v-if="unread" class="ai-unread">{{ unread > 99 ? '99+' : unread }}</span>
  </button>
</template>

<style scoped>
/* 右下角浮窗（主页）；折叠时只保留入口按钮 */
.global-ai-panel {
  position: fixed;
  right: 18px;
  bottom: 18px;
  z-index: 2000;
  width: 400px;
  max-width: calc(100vw - 36px);
  height: min(560px, calc(100vh - 36px));
  display: flex;
  flex-direction: column;
  gap: 8px;
  box-sizing: border-box;
  padding: 10px 12px 12px;
  background: var(--bg-color);
  border: 1px solid var(--border-color);
  border-radius: 12px;
  box-shadow: 0 6px 24px rgba(0, 0, 0, 0.18);
}
.global-ai-header { flex: none; display: flex; align-items: center; gap: 8px; }
.global-ai-title { margin: 0; font-size: 13px; color: var(--text-color); font-weight: 600; letter-spacing: 0.5px; }
.global-ai-sub { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; color: var(--text-secondary); }
.mini-icon {
  border: 1px solid transparent; background: transparent; color: var(--text-secondary);
  width: 24px; height: 24px; border-radius: 6px; cursor: pointer; font-size: 12px; line-height: 1; flex: none;
}
.mini-icon:hover { border-color: var(--border-color); background: var(--panel-bg); color: var(--primary-color); }

.chat-body { flex: 1; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; padding: 2px; }
.chat-empty { color: var(--text-secondary); font-size: 13px; line-height: 1.8; padding: 6px 2px; }
.chat-msg { display: flex; flex-direction: column; gap: 4px; font-size: 13px; }
.chat-msg.user .chat-content { background: var(--primary-color); color: #fff; padding: 8px 10px; border-radius: 8px; white-space: pre-wrap; }
.chat-msg.assistant .chat-content { background: var(--panel-bg); padding: 8px 10px; border-radius: 8px; overflow-x: auto; min-width: 0; } /* 三审 Moderate-2：长 KaTeX 公式横向可滚动 */
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
.chat-copy { border: none; background: transparent; color: #909399; font-size: 13px; cursor: pointer; padding: 0 2px; }
.chat-copy:hover { color: var(--primary-color); }
.chat-toolbar { flex: none; display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.chat-toolbar-actions { flex: none; display: flex; align-items: center; gap: 2px; }
.chat-context { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; color: var(--text-secondary); }
.ai-input-row { flex: none; display: flex; gap: 6px; align-items: flex-end; }
.ai-input {
  flex: 1; height: 64px; resize: none;
  border: 1px solid var(--border-color); border-radius: 6px; padding: 8px 10px;
  background: var(--panel-bg); color: var(--text-color); font-family: inherit; font-size: 13px;
}
.ai-input:focus { outline: none; border-color: var(--primary-color); }
.ai-input:disabled { opacity: 0.6; }

/* 折叠入口（右下角悬浮按钮） */
.global-ai-fab {
  position: fixed;
  right: 18px;
  bottom: 18px;
  z-index: 2000;
  display: flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--border-color);
  border-radius: 999px;
  padding: 10px 16px;
  background: var(--panel-bg);
  color: var(--text-color);
  cursor: pointer;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.16);
  font-size: 13px;
  position: relative;
}
.global-ai-fab:hover { border-color: var(--primary-color); color: var(--primary-color); }
.fab-icon { font-size: 16px; }
.ai-live-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--status-ok); animation: blink 1s step-start infinite; }
.ai-unread {
  position: absolute;
  top: -6px;
  right: -6px;
  min-width: 18px;
  height: 18px;
  line-height: 18px;
  text-align: center;
  font-size: 11px;
  color: #fff;
  background: var(--status-err);
  border-radius: 9px;
  padding: 0 4px;
}
</style>
