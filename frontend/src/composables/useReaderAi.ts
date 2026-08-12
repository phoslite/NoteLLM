import { computed, reactive, ref, watch, type ComputedRef, type Ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { clearChatMessages, listChatMessages, streamChat } from '@/api/chat'
import { mergeChatHistory } from '@/utils/chatMerge'
import { useStreamSession } from '@/composables/useStreamSession'
import { uuid } from '@/utils/streamCore'
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

/**
 * AI 助手（MO3 薄适配层）：按章节上下文流式问答、预设能力按钮、划词追问、清空与复制。
 * 流式内核（缓冲/节流 flush/公式未闭合延迟/思考折叠/2s 轮询补偿/streamSeq 终态机/中止释放）
 * 已抽取至 useStreamSession；本层只保留差异化状态：消息池、模式切换、历史加载、
 * 清空确认、会话键、划词/滚动注入。
 */
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
  let pendingSelection = ''
  let historySeq = 0
  // 会话标识（决策 34）：同会话内后端复用 LLM 挑选结果；换书/换模式/清空后重新生成
  let sessionId = ''
  function newSession() {
    sessionId = uuid()
  }
  newSession()
  watch(bookId, () => newSession())

  // 一次发送的流参数快照：fetchStream 在 stream() 内同步调用，读取最近一次发送的参数
  let sendParams: { question: string; selection?: string; crop_image?: string; crop_label?: string; stream_key: string } | null = null
  const session = useStreamSession({
    fetchStream: (onEvent) => {
      const p = sendParams!
      return streamChat(
        bookId.value,
        { question: p.question, chapter_id: currentChapterId.value, selection: p.selection, crop_image: p.crop_image, crop_label: p.crop_label, mode: chatMode.value, session_id: sessionId, stream_key: p.stream_key },
        onEvent,
      )
    },
    pollHistory: () => listChatMessages(bookId.value, chatMode.value),
    // 差异点①③：reader 在 flush 增量、轮询补差后滚动聊天区（内核 finally 兜底滚动）
    scrollToBottom: scrollChat,
    // end 终态 / F2 无终态收尾（非 abort）时通知未读角标
    onFinal: onAssistantDone,
    removeAssistant: (assistant) => {
      chatMessages.value = chatMessages.value.filter((m) => m !== assistant)
    },
  })
  const { streaming, streamError } = session

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
      // C-I2：合并而非整体替换——本地流式消息保留，在途流的 DB 部分行按 stream_key 排除，
      // 已落库消息按「角色+内容」去重（修复「输出需刷新才可见」与折叠再展开重复）
      chatMessages.value = mergeChatHistory(current, rows)
    } catch {
      /* 历史加载失败不影响阅读 */
    }
  }

  /** 切换会话模式（默认/解读/概论/思考逻辑）：中断进行中的流、重载该模式历史。 */
  function switchMode(mode: string) {
    if (mode === chatMode.value) return
    if (streaming.value) abortChat()
    chatMode.value = mode
    // C-I1：先清空旧模式池的本地消息再加载新历史——否则旧消息会被合并逻辑
    // 当作 extras 追加到新模式历史尾部，四个能力池互相串台（决策 30 分池失效）
    chatMessages.value = []
    pendingSelection = ''
    streamError.value = ''
    newSession() // 模式分池视为独立会话（决策 30/34）
    return loadChatHistory()
  }

  function resetChat() {
    if (streaming.value) abortChat()
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
    // 方案 A（v1.138）：芯片仅切池并预填标准提示词，由用户确认后手动发送——
    // 避免误触直接消耗 token，也便于发送前编辑提示词
  }

  async function sendChat(opts?: { crop_image?: string; crop_label?: string }) {
    const question = aiInput.value.trim()
    if (!question || streaming.value) return
    if (!currentChapterId.value) {
      // P2-3（v1.138）：无章节（空书/章节加载中）时给出明确反馈，不再静默失败
      ElMessage.warning('请先选择章节后再向 AI 提问')
      return
    }
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
    const streamKey = uuid()
    const assistant = reactive<UiChatMsg>({
      id: Date.now() + 1, role: 'assistant', content: '', local: true,
      book_id: bookId.value, chapter_id: currentChapterId.value, ref_para_pos: null, created_at: null,
      stream_key: streamKey,
    })
    chatMessages.value.push(assistant)
    sendParams = { question, selection, crop_image: opts?.crop_image, crop_label: opts?.crop_label, stream_key: streamKey }
    await session.stream(assistant, streamKey)
  }

  /** 用户主动中断（阅读页侧命名）。 */
  function abortChat() {
    session.abort()
  }

  /** 卸载清理（审查 N-3/N-13）：中止进行中的流与历史轮询定时器。 */
  function dispose() {
    session.dispose()
  }

  async function clearChat() {
    // C-1（E2E 2026-08-11）：清空为不可逆操作，必须先确认；范围 = 本书当前模式池（该模式唯一会话）
    // 二轮复核：abortChat 移到确认成功后执行——用户取消确认时不得误杀在途流
    const modeLabel = chatMode.value || '默认'
    try {
      await ElMessageBox.confirm(
        `将永久删除本书「${modeLabel}」模式的全部聊天记录（共 ${chatMessages.value.length} 条），此操作不可恢复。确定清空？`,
        '清空对话',
        { type: 'warning', confirmButtonText: '清空', cancelButtonText: '取消' },
      )
    } catch {
      return // 用户取消
    }
    try {
      if (streaming.value) abortChat()
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