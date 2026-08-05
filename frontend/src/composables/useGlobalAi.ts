import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { clearGlobalChatMessages, deleteGlobalChatSession, listGlobalChatMessages, streamGlobalChat } from '@/api/chat'
import type { ChatMessageItem } from '@/types'

export type UiGlobalMsg = ChatMessageItem & {
  local?: boolean
  citations?: { chapter: number; para: string }[]
  cached?: boolean
  /** 流式中模型的思考过程（DeepSeek reasoning_content 等，不落库）。 */
  thinking?: string
}

export interface GlobalAi {
  messages: import('vue').Ref<UiGlobalMsg[]>
  input: import('vue').Ref<string>
  streaming: import('vue').Ref<boolean>
  streamError: import('vue').Ref<string>
  send: () => Promise<void>
  abort: () => void
  clear: () => Promise<void>
  /** 删除当前会话（历史 + 挑选缓存）并换新会话键，重开面板为全新对话。 */
  deleteSession: () => Promise<void>
  copy: (text: string) => void
  /** 重新拉取该会话全部历史（展开面板时调用；与本地未落库消息按角色+内容去重合并）。 */
  refreshHistory: () => Promise<void>
  dispose: () => void
}

/** 渲染节流（同阅读页）：每 80ms 批量刷出；公式未闭合时最多等待 500ms。 */
const FLUSH_INTERVAL_MS = 80
const MATH_MAX_WAIT_MS = 500
/** 方案2：流式期间固定频率轮询历史（SSE 静默/丢失时自动补增量）。 */
const POLL_INTERVAL_MS = 2000
const THINKING_FLUSH_MS = 150

/** 检测缓冲区尾部是否有未闭合的 $$…$$ 或 $…$（避免流式中 KaTeX 闪错）。 */
function hasUnclosedMath(text: string): boolean {
  const blockPairs = (text.match(/\$\$/g) ?? []).length
  const inlineDollars = (text.replace(/\$\$/g, '').match(/\$/g) ?? []).length
  return blockPairs % 2 === 1 || inlineDollars % 2 === 1
}

/**
 * 决策 37：主页全局 AI 对话——不绑定书籍/章节，注入全局 Skill + 跨书 RAG（LLM 挑选）。
 * 流式输出复用方案2（stream_key 滚动落库 + 2s 轮询补增量），输出 Markdown/LaTeX 渲染。
 */
export function useGlobalAi(): GlobalAi {
  const messages = ref<UiGlobalMsg[]>([])
  const input = ref('')
  const streaming = ref(false)
  const streamError = ref('')
  let chatAbort: (() => void) | null = null
  let activePollTimer: number | null = null
  // 会话标识（需求 v1.73）：localStorage 持久化——重开面板/刷新页面仍载入原对话历史
  // （global:{session_id}）；历史与挑选缓存共用该键。
  const SESSION_STORAGE_KEY = 'global_ai_session_id'
  function loadOrCreateSession(): string {
    try {
      const saved = localStorage.getItem(SESSION_STORAGE_KEY)
      if (saved) return saved
    } catch {
      /* 隐私模式等场景忽略，每次生成新会话 */
    }
    const fresh = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`
    try {
      localStorage.setItem(SESSION_STORAGE_KEY, fresh)
    } catch {
      /* 忽略写入失败 */
    }
    return fresh
  }
  let sessionId = loadOrCreateSession()

  let pendingText = ''
  let flushTimer: ReturnType<typeof setTimeout> | null = null
  let lastFlushAt = 0

  function flushDelta(assistant: UiGlobalMsg) {
    if (flushTimer !== null) {
      clearTimeout(flushTimer)
      flushTimer = null
    }
    if (!pendingText) return
    assistant.content += pendingText
    pendingText = ''
    lastFlushAt = Date.now()
  }

  function scheduleFlush(assistant: UiGlobalMsg) {
    if (flushTimer !== null) return
    flushTimer = setTimeout(() => {
      flushTimer = null
      if (hasUnclosedMath(pendingText) && Date.now() - lastFlushAt < MATH_MAX_WAIT_MS) {
        scheduleFlush(assistant)
        return
      }
      flushDelta(assistant)
    }, FLUSH_INTERVAL_MS)
  }

  /** 方案2：流式期间固定频率轮询历史；SSE 静默/丢失时用已落库增量补全本地消息。 */
  async function pollStreamHistory(assistant: UiGlobalMsg, streamKey: string) {
    try {
      const rows = await listGlobalChatMessages(sessionId)
      const row = rows.find((r) => r.role === 'assistant' && r.stream_key === streamKey)
      if (row && row.content.length > assistant.content.length) {
        assistant.content = row.content
      }
    } catch {
      /* 轮询失败忽略：SSE 仍为主通道 */
    }
  }

  async function loadHistory() {
    try {
      const rows = await listGlobalChatMessages(sessionId)
      if (!messages.value.length) {
        messages.value = rows
        return
      }
      // 合并而非整体替换：本地流式消息（local）保留；已落库消息按「角色+内容」与历史行去重
      const seen = new Set(rows.map((r) => `${r.role}:${r.content}`))
      const extras = messages.value.filter((m) => m.local || !seen.has(`${m.role}:${m.content}`))
      messages.value = extras.length ? [...rows, ...extras] : rows
    } catch {
      /* 历史加载失败不影响使用 */
    }
  }

  async function send() {
    const question = input.value.trim()
    if (!question || streaming.value) return
    input.value = ''
    streamError.value = ''
    messages.value.push({
      id: Date.now(), role: 'user', content: question,
      book_id: null, chapter_id: null, ref_para_pos: null, created_at: null,
    })
    // reactive() 包裹：流中直接改 content/thinking 能触发 Vue 渲染
    const streamKey = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`
    const assistant = reactive<UiGlobalMsg>({
      id: Date.now() + 1, role: 'assistant', content: '', local: true,
      book_id: null, chapter_id: null, ref_para_pos: null, created_at: null,
      stream_key: streamKey,
    })
    messages.value.push(assistant)
    streaming.value = true
    pendingText = ''
    lastFlushAt = Date.now()
    let pendingThinking = ''
    let thinkingFlushAt = Date.now()
    function flushThinking() {
      if (!pendingThinking) return
      assistant.thinking = (assistant.thinking ?? '') + pendingThinking
      pendingThinking = ''
      thinkingFlushAt = Date.now()
    }
    activePollTimer = setInterval(() => {
      void pollStreamHistory(assistant, streamKey)
    }, POLL_INTERVAL_MS)
    const { promise, abort } = streamGlobalChat(
      { question, session_id: sessionId, stream_key: streamKey },
      (ev) => {
        if (ev.type === 'thinking') {
          pendingThinking += ev.text
          if (Date.now() - thinkingFlushAt >= THINKING_FLUSH_MS) flushThinking()
        } else if (ev.type === 'delta') {
          pendingText += ev.text
          scheduleFlush(assistant)
        } else if (ev.type === 'end') {
          flushThinking()
          flushDelta(assistant)
          assistant.content = ev.text
          assistant.citations = ev.citations
          assistant.cached = ev.cached
          assistant.local = false
          streaming.value = false
          if (activePollTimer !== null) {
            clearInterval(activePollTimer)
            activePollTimer = null
          }
        } else if (ev.type === 'error') {
          flushThinking()
          flushDelta(assistant)
          streaming.value = false
          streamError.value = ev.message
          if (activePollTimer !== null) {
            clearInterval(activePollTimer)
            activePollTimer = null
          }
        }
      },
    )
    chatAbort = abort
    try {
      await promise
    } catch (err) {
      // 用户主动中断（abort）不提示；其余错误提示
      if (!(err instanceof DOMException && err.name === 'AbortError')) {
        streamError.value = err instanceof Error ? err.message : String(err)
        streaming.value = false
        if (activePollTimer !== null) {
          clearInterval(activePollTimer)
          activePollTimer = null
        }
      }
    }
    chatAbort = null
  }

  function abortChat() {
    chatAbort?.()
  }

  async function clear() {
    if (streaming.value) chatAbort?.()
    try {
      await clearGlobalChatMessages(sessionId)
      messages.value = []
      streamError.value = ''
      // 保持同一会话键（localStorage 持久化）：清空后新对话仍写入原会话，
      // 重开面板可载入新积累的历史；挑选缓存随会话键延续（TTL 自然过期）
    } catch (err) {
      ElMessage.error(err instanceof Error ? err.message : '清空失败')
    }
  }

  async function deleteSession() {
    if (streaming.value) chatAbort?.()
    try {
      await deleteGlobalChatSession(sessionId)
      messages.value = []
      streamError.value = ''
      // 旧会话（历史 + 挑选缓存）已删除：重置会话键，重开面板即全新对话
      try {
        localStorage.removeItem(SESSION_STORAGE_KEY)
      } catch {
        /* 忽略写入失败 */
      }
      sessionId = loadOrCreateSession()
    } catch (err) {
      ElMessage.error(err instanceof Error ? err.message : '删除会话失败')
    }
  }

  function copy(text: string) {
    void navigator.clipboard?.writeText(text).catch(() => ElMessage.warning('复制失败'))
  }

  function dispose() {
    chatAbort?.()
    if (activePollTimer !== null) {
      clearInterval(activePollTimer)
      activePollTimer = null
    }
    if (flushTimer !== null) {
      clearTimeout(flushTimer)
      flushTimer = null
    }
  }

  void loadHistory()

  return {
    messages, input, streaming, streamError,
    send, abort: abortChat, clear, deleteSession, copy,
    refreshHistory: () => loadHistory(),
    dispose,
  }
}
