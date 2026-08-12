import { reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { clearGlobalChatMessages, deleteGlobalChatSession, listGlobalChatMessages, streamGlobalChat } from '@/api/chat'
import { mergeChatHistory } from '@/utils/chatMerge'
import { useStreamSession } from '@/composables/useStreamSession'
import { uuid } from '@/utils/streamCore'
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

/**
 * 决策 37：主页全局 AI 对话——不绑定书籍/章节，注入全局 Skill + 跨书 RAG（LLM 挑选）。
 * 流式输出复用方案2（stream_key 滚动落库 + 2s 轮询补增量），输出 Markdown/LaTeX 渲染。
 * MO3 薄适配层：流式内核已抽取至 useStreamSession；本层保留消息池、会话键持久化、
 * 历史加载、清空/删除会话等差异化状态。
 */
export function useGlobalAi(): GlobalAi {
  const messages = ref<UiGlobalMsg[]>([])
  const input = ref('')
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
    const fresh = uuid()
    try {
      localStorage.setItem(SESSION_STORAGE_KEY, fresh)
    } catch {
      /* 忽略写入失败 */
    }
    return fresh
  }
  let sessionId = loadOrCreateSession()

  // 一次发送的流参数快照：fetchStream 在 stream() 内同步调用，读取最近一次发送的参数
  let sendParams: { question: string; stream_key: string } | null = null
  const session = useStreamSession({
    fetchStream: (onEvent) => {
      const p = sendParams!
      return streamGlobalChat({ question: p.question, session_id: sessionId, stream_key: p.stream_key }, onEvent)
    },
    pollHistory: () => listGlobalChatMessages(sessionId),
    // 无 scrollToBottom/onFinal：主页面板不随流滚动、无未读角标完成回调
    removeAssistant: (assistant) => {
      messages.value = messages.value.filter((m) => m !== assistant)
    },
  })
  const { streaming, streamError } = session

  async function loadHistory() {
    try {
      const rows = await listGlobalChatMessages(sessionId)
      if (!messages.value.length) {
        messages.value = rows
        return
      }
      // C-I2：合并而非整体替换——本地流式消息保留，在途流的 DB 部分行按 stream_key 排除，
      // 已落库消息按「角色+内容」去重（修复「输出需刷新才可见」与折叠再展开重复）
      messages.value = mergeChatHistory(messages.value, rows)
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
    const streamKey = uuid()
    const assistant = reactive<UiGlobalMsg>({
      id: Date.now() + 1, role: 'assistant', content: '', local: true,
      book_id: null, chapter_id: null, ref_para_pos: null, created_at: null,
      stream_key: streamKey,
    })
    messages.value.push(assistant)
    sendParams = { question, stream_key: streamKey }
    await session.stream(assistant, streamKey)
  }

  function abortChat() {
    session.abort()
  }

  async function clear() {
    // 审查 P1（v1.139）：清空为不可逆操作，须二次确认（与阅读页 clearChat 行为一致）
    try {
      await ElMessageBox.confirm(
        `将永久删除该会话的全部聊天记录（共 ${messages.value.length} 条），此操作不可恢复。确定清空？`,
        '清空对话',
        { type: 'warning', confirmButtonText: '清空', cancelButtonText: '取消' },
      )
    } catch {
      return // 用户取消：不误杀在途流
    }
    if (streaming.value) abortChat()
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
    if (streaming.value) abortChat()
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
    session.dispose()
  }

  void loadHistory()

  return {
    messages, input, streaming, streamError,
    send, abort: abortChat, clear, deleteSession, copy,
    refreshHistory: () => loadHistory(),
    dispose,
  }
}