import { computed, ref, type ComputedRef, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import { clearChatMessages, listChatMessages, streamChat } from '@/api/chat'
import type { ChapterItem, ChatMessageItem } from '@/types'

export type UiChatMsg = ChatMessageItem & { local?: boolean; citations?: { chapter: number; para: string }[]; cached?: boolean }

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
  clearChat: () => Promise<void>
  resetChat: () => void
  copyChat: (text: string) => void
  askSelection: () => void
}

/** 渲染节流（手册 §18）：每 80ms 批量刷出一次；公式未闭合时最多等待 500ms 再强制刷出。 */
const FLUSH_INTERVAL_MS = 80
const MATH_MAX_WAIT_MS = 500

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
}): ReaderAi {
  const { bookId, currentChapterId, currentChapter, scrollEl, takeSelection, openMindmap, scrollChat } = opts

  const chatMessages = ref<UiChatMsg[]>([])
  const chatMode = ref('')
  const aiInput = ref('')
  const streaming = ref(false)
  const streamError = ref('')
  let chatAbort: (() => void) | null = null
  let pendingSelection = ''
  let historySeq = 0
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
      chatMessages.value = rows
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
    void loadChatHistory()
  }

  function resetChat() {
    if (streaming.value) chatAbort?.()
    chatMessages.value = []
    streamError.value = ''
    void loadChatHistory()
  }

  function presetPrompt(kind: string) {
    if (kind === '脑图') {
      void openMindmap()
      return
    }
    if (['解读', '概论', '思考逻辑'].includes(kind)) switchMode(kind)
    const ch = currentChapter.value
    const ctx = ch ? `当前章节：第${ch.index}章「${ch.title}」。` : '当前未选择章节。'
    const prompts: Record<string, string> = {
      解读: `${ctx} 请对本章进行解读：先给出核心要义，再按段落解读，引用原文须标注【第X章 第Y段】出处。`,
      概论: `${ctx} 请为本章生成概论：概括主要内容、核心观点与关键结论，引用须标注出处。`,
      思考逻辑: `${ctx} 请梳理本章的思考逻辑：论证链条、关键假设与可追问的问题，引用须标注出处。`,
    }
    aiInput.value = prompts[kind] ?? ''
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
    const assistant: UiChatMsg = {
      id: Date.now() + 1, role: 'assistant', content: '', local: true,
      book_id: bookId.value, chapter_id: currentChapterId.value, ref_para_pos: null, created_at: null,
    }
    chatMessages.value.push(assistant)
    streaming.value = true
    pendingText = ''
    lastFlushAt = Date.now()
    const { promise, abort } = streamChat(
      bookId.value,
      { question, chapter_id: currentChapterId.value, selection, crop_image: opts?.crop_image, crop_label: opts?.crop_label, mode: chatMode.value },
      (ev) => {
        if (ev.type === 'delta') {
          pendingText += ev.text
          scheduleFlush(assistant)
        } else if (ev.type === 'end') {
          flushDelta(assistant)
          assistant.content = ev.text
          assistant.citations = ev.citations
          assistant.cached = ev.cached
          assistant.local = false
          streaming.value = false
        } else if (ev.type === 'error') {
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
      flushDelta(assistant)
      streaming.value = false
      streamError.value = (err as Error).message
    } finally {
      chatAbort = null
      if (!assistant.content && streamError.value) {
        chatMessages.value = chatMessages.value.filter((m) => m !== assistant)
      }
      scrollChat()
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
    presetPrompt, switchMode, sendChat, abortChat, clearChat, resetChat, copyChat, askSelection,
  }
}