import { computed, reactive, ref, watch, type ComputedRef, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import { clearChatMessages, listChatMessages, streamChat } from '@/api/chat'
import type { ChapterItem, ChatMessageItem } from '@/types'

export type UiChatMsg = ChatMessageItem & {
  local?: boolean
  citations?: { chapter: number; para: string }[]
  cached?: boolean
  /** 流式中模型的思考过程（DeepSeek reasoning_content 等，不落库）。 */
  thinking?: string
}

export interface ReaderAi {
  chatMessages: Ref<UiChatMsg[]>
  /** 会话模式：''=默认对话；解读/概论/思考逻辑=能力模式分池（决策 30）。 */
  chatMode: Ref<string>
  aiInput: Ref<string>
  streaming: Ref<boolean>
  streamError: Ref<string>
  currentChapterTitle: ComputedRef<string>
  presetPrompt: (kind: string) => void
  switchMode: (mode: string) => void
  sendChat: (opts?: { crop_image?: string; crop_label?: string }) => Promise<void>
  abortChat: () => void
  dispose: () => void
  clearChat: () => Promise<void>
  resetChat: () => void
  copyChat: (text: string) => void
  askSelection: () => void
}

/** 渲染节流（手册 §18）：每 80ms 批量刷出一次；公式未闭合时最多等待 500ms 再强制刷出。 */
const FLUSH_INTERVAL_MS = 80
const MATH_MAX_WAIT_MS = 500
/** 方案2：流式期间固定频率轮询历史（SSE 静默/丢失时自动补增量，无需刷新）。 */
const POLL_INTERVAL_MS = 2000
/** 思考过程渲染节流（thinking 事件可能高频小片）。 */
const THINKING_FLUSH_MS = 150

/** 检测缓冲区尾部是否有未闭合的 $$…$$ 或 $…$（避免流式中 KaTeX 闪错）。 */
function hasUnclosedMath(text: string): boolean {
  const blockPairs = (text.match(/\$\$/g) ?? []).length
  const inlineDollars = (text.replace(/\$\$/g, '').match(/\$/g) ?? []).length
  return blockPairs % 2 === 1 || inlineDollars % 2 === 1
}

/** AI 助手：按章节上下文流式问答、预设能力按钮、划词追问、清空与复制。 */
export function useReaderAi(opts: {
  bookId: ComputedRef<number>
  currentChapterId: Ref<number | null>
  currentChapter: ComputedRef<ChapterItem | undefined>
  scrollEl: Ref<HTMLElement | null>
  takeSelection: () => string
  openMindmap: (selection?: string) => void
  /** 流式输出时滚动聊天区到底部。 */
  scrollChat: () => void
  /** 有新 AI 回复完成时回调（折叠期间未读角标）。 */
  onAssistantDone?: () => void
}): ReaderAi {
  const { bookId, currentChapterId, currentChapter, scrollEl, takeSelection, openMindmap, scrollChat, onAssistantDone } = opts

  const chatMessages = ref<UiChatMsg[]>([])
  const chatMode = ref('')
  const aiInput = ref('')
  const streaming = ref(false)
  const streamError = ref('')
  let chatAbort: (() => void) | null = null
  let activePollTimer: number | null = null
  let pendingSelection = ''
  let historySeq = 0
  // 会话标识（决策 34）：同会话内后端复用 LLM 挑选结果；换书/换模式/清空后重新生成
  let sessionId = ''
  function newSession() {
    sessionId = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`
  }
  newSession()
  watch(bookId, () => newSession())
  // 流式渲染节流缓冲
  let pendingText = ''
  let flushTimer: ReturnType<typeof setTimeout> | null = null
  let lastFlushAt = 0

  const currentChapterTitle = computed(() => {
    const ch = currentChapter.value
    return ch ? `第${ch.index}章 ${ch.title}` : '未选择章节'
  })

  function currentSelection(): string {
    const sel = window.getSelection()
    const text = sel?.toString().trim() ?? ''
    if (!text || !sel?.anchorNode || !scrollEl.value) return ''
    return scrollEl.value.contains(sel.anchorNode) ? text : ''
  }

  async function loadChatHistory() {
    const seq = ++historySeq
    const mode = chatMode.value
    try {
      const rows = await listChatMessages(bookId.value, mode)
      if (seq !== historySeq) return // 已切换模式，丢弃过期响应
      const current = chatMessages.value
      if (!current.length) {
        chatMessages.value = rows
        return
      }
      // 合并而非整体替换：历史加载期间新发的本地消息（含流式中回复）不会被覆盖，
      // 已落库消息按「角色+内容」与历史行去重，避免重复（修复「输出需刷新才可见」）
      const extras = current.filter((m) => !rows.some((r) => r.role === m.role && r.content === m.content))
      chatMessages.value = extras.length ? [...rows, ...extras] : rows
    } catch {
      /* 历史加载失败不影响阅读 */
    }
  }

  /** 切换会话模式（默认/解读/概论/思考逻辑）：中断进行中的流、重载该模式历史。 */
  function switchMode(mode: string) {
    if (mode === chatMode.value) return
    if (streaming.value) chatAbort?.()
    chatMode.value = mode
    pendingSelection = ''
    streamError.value = ''
    newSession() // 模式分池视为独立会话（决策 30/34）
    return loadChatHistory()
  }

  function resetChat() {
    if (streaming.value) chatAbort?.()
    chatMessages.value = []
    streamError.value = ''
    void loadChatHistory()
  }

  async function presetPrompt(kind: string) {
    if (kind === '脑图') {
      void openMindmap()
      return
    }
    if (['解读', '概论', '思考逻辑'].includes(kind)) await switchMode(kind)
    const ch = currentChapter.value
    const ctx = ch ? `当前章节：第${ch.index}章「${ch.title}」。` : '当前未选择章节。'
    const prompts: Record<string, string> = {
      解读: `${ctx} 请对本章进行解读：先给出核心要义，再按段落解读，引用原文须标注【第X章 第Y段】出处。`,
      概论: `${ctx} 请为本章生成概论：概括主要内容、核心观点与关键结论，引用须标注出处。`,
      思考逻辑: `${ctx} 请梳理本章的思考逻辑：论证链条、关键假设与可追问的问题，引用须标注出处。`,
    }
    aiInput.value = prompts[kind] ?? ''
    void sendChat() // 一键生成：切换模式池后立即发起标准提示词（交互优化）
  }

  /** 把累积的缓冲一次性写入消息并滚动（渲染节流的核心刷出点）。 */
  function flushDelta(assistant: UiChatMsg) {
    if (flushTimer !== null) {
      clearTimeout(flushTimer)
      flushTimer = null
    }
    if (!pendingText) return
    assistant.content += pendingText
    pendingText = ''
    lastFlushAt = Date.now()
    scrollChat()
  }

  /** 计划下一次批量刷出；公式未闭合且等待未超时则推迟。 */
  function scheduleFlush(assistant: UiChatMsg) {
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
  async function pollStreamHistory(assistant: UiChatMsg, streamKey: string) {
    try {
      const rows = await listChatMessages(bookId.value, chatMode.value)
      const row = rows.find((r) => r.role === 'assistant' && r.stream_key === streamKey)
      if (row && row.content.length > assistant.content.length) {
        assistant.content = row.content
        scrollChat()
      }
    } catch {
      /* 轮询失败忽略：SSE 仍为主通道 */
    }
  }

  async function sendChat(opts?: { crop_image?: string; crop_label?: string }) {
    const question = aiInput.value.trim()
    if (!question || streaming.value || !currentChapterId.value) return
    aiInput.value = ''
    const selection = pendingSelection || currentSelection() || undefined
    pendingSelection = ''
    streamError.value = ''
    chatMessages.value.push({
      id: Date.now(), role: 'user', content: question,
      book_id: bookId.value, chapter_id: currentChapterId.value, ref_para_pos: null, created_at: null,
    })
    // reactive() 包裹：流中直接改 content/thinking 能触发 Vue 渲染（普通对象变更不重渲染，
    // 这是「输出需刷新才可见」的根因之一）；stream_key 供后端滚动落库、前端轮询匹配。
    const streamKey = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`
    const assistant = reactive<UiChatMsg>({
      id: Date.now() + 1, role: 'assistant', content: '', local: true,
      book_id: bookId.value, chapter_id: currentChapterId.value, ref_para_pos: null, created_at: null,
      stream_key: streamKey,
    })
    chatMessages.value.push(assistant)
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
    const { promise, abort } = streamChat(
      bookId.value,
      { question, chapter_id: currentChapterId.value, selection, crop_image: opts?.crop_image, crop_label: opts?.crop_label, mode: chatMode.value, session_id: sessionId, stream_key: streamKey },
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
          onAssistantDone?.()
        } else if (ev.type === 'error') {
          flushThinking()
          flushDelta(assistant)
          streaming.value = false
          streamError.value = ev.message
        }
      },
    )
    chatAbort = abort
    try {
      await promise
    } catch (err) {
      flushThinking()
      flushDelta(assistant)
      streaming.value = false
      streamError.value = (err as Error).message
    } finally {
      if (activePollTimer != null) {
        clearInterval(activePollTimer)
        activePollTimer = null
      }
      chatAbort = null
      if (!assistant.content && streamError.value) {
        chatMessages.value = chatMessages.value.filter((m) => m !== assistant)
      }
      scrollChat()
    }
  }

  /** 卸载清理（审查 N-3/N-13）：中止进行中的流与历史轮询定时器。 */
  function dispose() {
    abortChat()
    if (activePollTimer != null) {
      clearInterval(activePollTimer)
      activePollTimer = null
    }
    if (flushTimer != null) {
      clearTimeout(flushTimer)
      flushTimer = null
    }
  }

  function abortChat() {
    chatAbort?.()
  }

  async function clearChat() {
    if (streaming.value) abortChat()
    try {
      await clearChatMessages(bookId.value, chatMode.value)
      chatMessages.value = []
      streamError.value = ''
      newSession() // 新对话 = 新会话（挑选缓存重新生效）
    } catch (err) {
      ElMessage.error((err as Error).message)
    }
  }

  function copyChat(text: string) {
    if (!text) return
    navigator.clipboard
      .writeText(text)
      .then(() => ElMessage.success('已复制'))
      .catch(() => ElMessage.error('复制失败'))
  }

  function askSelection() {
    const sel = takeSelection()
    if (!sel) return
    pendingSelection = sel
    aiInput.value = `请解读我选中的这段内容，引用须标注【第X章 第Y段】出处：\n${sel}`
    void sendChat()
  }

  return {
    chatMessages, chatMode, aiInput, streaming, streamError, currentChapterTitle,
    presetPrompt, switchMode, sendChat, abortChat, dispose, clearChat, resetChat, copyChat, askSelection,
  }
}