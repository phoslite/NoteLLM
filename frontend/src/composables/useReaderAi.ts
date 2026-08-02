import { computed, ref, type ComputedRef, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import { clearChatMessages, listChatMessages, streamChat } from '@/api/chat'
import type { ChapterItem, ChatMessageItem } from '@/types'

export type UiChatMsg = ChatMessageItem & { local?: boolean; citations?: { chapter: number; para: string }[] }

export interface ReaderAi {
  chatMessages: Ref<UiChatMsg[]>
  aiInput: Ref<string>
  streaming: Ref<boolean>
  streamError: Ref<string>
  currentChapterTitle: ComputedRef<string>
  presetPrompt: (kind: string) => void
  sendChat: (opts?: { crop_image?: string; crop_label?: string }) => Promise<void>
  abortChat: () => void
  clearChat: () => Promise<void>
  resetChat: () => void
  copyChat: (text: string) => void
  askSelection: () => void
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
  const aiInput = ref('')
  const streaming = ref(false)
  const streamError = ref('')
  let chatAbort: (() => void) | null = null
  let pendingSelection = ''

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
    try {
      chatMessages.value = await listChatMessages(bookId.value)
    } catch {
      /* 历史加载失败不影响阅读 */
    }
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
    const ch = currentChapter.value
    const ctx = ch ? `当前章节：第${ch.index}章「${ch.title}」。` : '当前未选择章节。'
    const prompts: Record<string, string> = {
      解读: `${ctx} 请对本章进行解读：先给出核心要义，再按段落解读，引用原文须标注【第X章 第Y段】出处。`,
      概论: `${ctx} 请为本章生成概论：概括主要内容、核心观点与关键结论，引用须标注出处。`,
      思考逻辑: `${ctx} 请梳理本章的思考逻辑：论证链条、关键假设与可追问的问题，引用须标注出处。`,
    }
    aiInput.value = prompts[kind] ?? ''
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
    const { promise, abort } = streamChat(
      bookId.value,
      { question, chapter_id: currentChapterId.value, selection, crop_image: opts?.crop_image, crop_label: opts?.crop_label },
      (ev) => {
        if (ev.type === 'delta') {
          assistant.content += ev.text
        } else if (ev.type === 'end') {
          assistant.content = ev.text
          assistant.citations = ev.citations
          assistant.local = false
          streaming.value = false
        } else if (ev.type === 'error') {
          streaming.value = false
          streamError.value = ev.message
        }
        scrollChat()
      },
    )
    chatAbort = abort
    try {
      await promise
    } catch (err) {
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
      await clearChatMessages(bookId.value)
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
    chatMessages, aiInput, streaming, streamError, currentChapterTitle,
    presetPrompt, sendChat, abortChat, clearChat, resetChat, copyChat, askSelection,
  }
}
