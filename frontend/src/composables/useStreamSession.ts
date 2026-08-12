import { ref, type Ref } from 'vue'
import type { ChatMessageItem, ChatStreamEvent } from '@/types'
import {
  FLUSH_INTERVAL_MS, MATH_MAX_WAIT_MS, POLL_INTERVAL_MS, SSE_ACTIVE_GUARD_MS,
  THINKING_FLUSH_MS, hasUnclosedMath, isAbortError,
} from '@/utils/streamCore'

/** 流式助手气泡（适配层 UiChatMsg/UiGlobalMsg 结构兼容此类型）。 */
export type StreamAssistant = ChatMessageItem & {
  local?: boolean
  citations?: { chapter: number; para: string }[]
  cached?: boolean
  /** 流式中模型的思考过程（DeepSeek reasoning_content 等，不落库）。 */
  thinking?: string
}

export interface StreamSessionOptions {
  /** 发起 SSE 流（onEvent 由内核传入；发送参数经适配层闭包快照携带）。 */
  fetchStream: (onEvent: (ev: ChatStreamEvent) => void) => { promise: Promise<void>; abort: () => void }
  /** 轮询历史行（差异点②：listChatMessages(bookId, mode) vs listGlobalChatMessages(sessionId)）。 */
  pollHistory: () => Promise<ChatMessageItem[]>
  /** 有增量写出时滚动聊天区（差异点①③：reader 注入 scrollChat；global 不注入）。 */
  scrollToBottom?: () => void
  /** 完成回调（end 终态或 F2 无终态收尾且非 abort；reader 注入未读角标 onAssistantDone）。 */
  onFinal?: () => void
  /** delta 文本扩展钩子（当前适配层不用，供未来流式调用方）。 */
  onDelta?: (text: string) => void
  /** 错误消息钩子（error 事件 / 非 abort 的 catch；当前由内核 streamError ref 覆盖展示）。 */
  onError?: (message: string) => void
  /** 终态后移除空气泡（差异点：各自操作 chatMessages/messages 列表）。 */
  removeAssistant?: (assistant: StreamAssistant) => void
  flushIntervalMs?: number
  mathMaxWaitMs?: number
  pollIntervalMs?: number
  thinkingFlushMs?: number
}

export interface StreamSession {
  streaming: Ref<boolean>
  streamError: Ref<string>
  /** 发起一次流式会话：适配层先构造 assistant 气泡并推入列表，再调用本方法。 */
  stream: (assistant: StreamAssistant, streamKey: string) => Promise<void>
  /** 用户点「停止」：推进流代际并中断 SSE。 */
  abort: () => void
  /** 卸载清理：推进流代际 + 中断 + 清轮询/节流定时器。 */
  dispose: () => void
}

/**
 * MO3 流式会话内核（第 6 轮抽取）：收敛 useReaderAi/useGlobalAi 重复约 66% 的
 * 流式缓冲、节流 flush、公式未闭合延迟、思考折叠 flush、2s 轮询补偿、
 * streamSeq 终态机（end/error/catch/F2/dispose/abortChat 六分支自增）与中止/释放。
 * 行为契约：F1 停止复位、F2 无终态复位、I-2 在途轮询不写已终态气泡、
 * I-4/I-13 SSE 活跃期防重放与轮询差量前缀对齐；差异点全部经 options 注入，
 * 不写死 reader/global 专属逻辑（第三个流式调用方可直接复用）。
 */
export function useStreamSession(options: StreamSessionOptions): StreamSession {
  const {
    fetchStream, pollHistory, scrollToBottom, onFinal, onDelta, onError, removeAssistant,
    flushIntervalMs = FLUSH_INTERVAL_MS,
    mathMaxWaitMs = MATH_MAX_WAIT_MS,
    pollIntervalMs = POLL_INTERVAL_MS,
    thinkingFlushMs = THINKING_FLUSH_MS,
  } = options

  const streaming = ref(false)
  const streamError = ref('')
  let chatAbort: (() => void) | null = null
  let activePollTimer: number | null = null
  // 流式渲染节流缓冲
  let pendingText = ''
  let flushTimer: ReturnType<typeof setTimeout> | null = null
  let lastFlushAt = 0
  let streamSeq = 0 // 流代际守卫（审查 I-2）：abort/切书后在途轮询响应直接丢弃
  let lastSseActivityAt = 0 // 最近一次 SSE 事件时刻；活跃期（<SSE_ACTIVE_GUARD_MS）不做 DB 补差，防尾部重放重复
  // P2-5（v1.138）：当前在途流的轮询上下文——页面隐藏时暂停 2s 轮询，恢复可见后自动续跑（省电/减后端压力）
  let pollCtx: { assistant: StreamAssistant; streamKey: string; seq: number } | null = null

  function stopPolling() {
    if (activePollTimer != null) {
      clearInterval(activePollTimer)
      activePollTimer = null
    }
  }

  function startPolling() {
    if (activePollTimer != null) return
    if (!pollCtx) return
    const ctx = pollCtx
    activePollTimer = setInterval(() => {
      void pollStreamHistory(ctx.assistant, ctx.streamKey, ctx.seq)
    }, pollIntervalMs)
  }

  function onVisibilityChange() {
    if (typeof document === 'undefined') return // 非浏览器环境（SSR/单测）守卫
    if (document.visibilityState === 'hidden') {
      stopPolling()
    } else if (streaming.value && pollCtx) {
      startPolling() // 隐藏期间流仍在走（SSE 主通道），恢复可见后重新用 2s 轮询补差
    }
  }
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', onVisibilityChange)
  }

  /** 把累积的缓冲一次性写入消息并滚动（渲染节流的核心刷出点）。 */
  function flushDelta(assistant: StreamAssistant) {
    if (flushTimer !== null) {
      clearTimeout(flushTimer)
      flushTimer = null
    }
    if (!pendingText) return
    assistant.content += pendingText
    pendingText = ''
    lastFlushAt = Date.now()
    scrollToBottom?.()
  }

  /** 计划下一次批量刷出；公式未闭合且等待未超时则推迟。 */
  function scheduleFlush(assistant: StreamAssistant) {
    if (flushTimer !== null) return
    flushTimer = setTimeout(() => {
      flushTimer = null
      if (hasUnclosedMath(pendingText) && Date.now() - lastFlushAt < mathMaxWaitMs) {
        scheduleFlush(assistant)
        return
      }
      flushDelta(assistant)
    }, flushIntervalMs)
  }

  /** 方案2：流式期间固定频率轮询历史；SSE 静默/丢失时用已落库增量补全本地消息。 */
  async function pollStreamHistory(assistant: StreamAssistant, streamKey: string, seq: number) {
    if (seq !== streamSeq) return // 流代际守卫：旧流的在途轮询响应不写共享 pendingText
    if (Date.now() - lastSseActivityAt < SSE_ACTIVE_GUARD_MS) return // SSE 活跃期不补差（审查 I-2）
    try {
      const rows = await pollHistory()
      const row = rows.find((r) => r.role === 'assistant' && r.stream_key === streamKey)
      if (row && row.content.length > assistant.content.length) {
        // I-13 修复：以「已显示 + 未刷出」为本地完整状态做前缀对齐，
        // 只补差量到 pendingText；整体覆盖会与后续 flushDelta 重复追加。
        const localFull = assistant.content + pendingText
        if (row.content.startsWith(localFull)) {
          const extra = row.content.slice(assistant.content.length)
          if (extra) {
            pendingText = extra
            scheduleFlush(assistant) // 审查 C-1：SSE 静默时轮询补增量必须触发渲染
          }
        } else if (!row.content.startsWith(assistant.content)) {
          // 审查 I-4：DB 落后于本地缓冲时保持 pendingText；仅服务端改写才整体覆盖
          assistant.content = row.content
          pendingText = ''
        }
        scrollToBottom?.()
      }
    } catch {
      /* 轮询失败忽略：SSE 仍为主通道 */
    }
  }

  async function stream(assistant: StreamAssistant, streamKey: string): Promise<void> {
    streaming.value = true
    streamError.value = ''
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
    const seq = ++streamSeq
    lastSseActivityAt = Date.now()
    // 同步抛错防御（第 7 轮 Ptolemy F1）：fetchStream 同步抛错（如适配层 sendParams
    // 快照缺失/参数非法）时必须复位 streaming 且不启动轮询，避免 streaming 永久卡
    // true + 轮询定时器泄漏；异步失败仍走下方 catch/finally 终态机。
    let terminalSeen = false
    let wasAborted = false
    let streamHandle: { promise: Promise<void>; abort: () => void }
    try {
      streamHandle = fetchStream((ev) => {
      if (ev.type === 'thinking') {
        lastSseActivityAt = Date.now()
        pendingThinking += ev.text
        if (Date.now() - thinkingFlushAt >= thinkingFlushMs) flushThinking()
      } else if (ev.type === 'delta') {
        lastSseActivityAt = Date.now()
        pendingText += ev.text
        onDelta?.(ev.text)
        scheduleFlush(assistant)
      } else if (ev.type === 'end') {
        terminalSeen = true
        streamSeq += 1 // MO2（四轮）：终态分支推进代际，在途轮询响应不再写缓冲
        flushThinking()
        flushDelta(assistant)
        assistant.content = ev.text
        assistant.citations = ev.citations
        assistant.cached = ev.cached
        assistant.local = false
        streaming.value = false
        stopPolling()
        onFinal?.()
      } else if (ev.type === 'error') {
        terminalSeen = true
        streamSeq += 1 // MO2（四轮）：终态分支推进代际，在途轮询响应不再写缓冲
        flushThinking()
        flushDelta(assistant)
        assistant.local = false // P1-2（v1.138）：终态后不再显示流式闪烁光标
        streaming.value = false
        streamError.value = ev.message
        stopPolling()
        onError?.(ev.message)
      }
      })
    } catch (err) {
      streaming.value = false
      const message = err instanceof Error ? err.message : String(err)
      streamError.value = message
      onError?.(message)
      if (!assistant.content) removeAssistant?.(assistant)
      return
    }
    pollCtx = { assistant, streamKey, seq }
    startPolling()
    const { promise, abort } = streamHandle
    chatAbort = abort
    try {
      await promise
    } catch (err) {
      streamSeq += 1 // MO2（四轮）：错误分支同样推进代际，在途轮询响应不再写缓冲
      wasAborted = isAbortError(err)
      flushThinking()
      flushDelta(assistant)
      assistant.local = false // P1-2（v1.138）：中止/出错后不再显示流式闪烁光标
      streaming.value = false
      // 用户主动中断（abort）不显示误导性错误横幅
      if (!wasAborted) {
        const message = err instanceof Error ? err.message : String(err)
        streamError.value = message
        onError?.(message)
      }
    } finally {
      stopPolling()
      pollCtx = null
      if (flushTimer !== null) {
        clearTimeout(flushTimer)
        flushTimer = null
      }
      chatAbort = null
      // F2 兜底：SSE 连接正常结束但未收到 end/error 终态（代理截断、服务端未 flush 终态）时复位
      if (!terminalSeen) {
        streamSeq += 1 // MO2（四轮）：F2 兜底分支同样推进代际
        flushThinking()
        flushDelta(assistant)
        assistant.local = false // P1-2（v1.138）：无终态收尾后不再显示流式闪烁光标
        streaming.value = false
        if (!wasAborted) onFinal?.()
      }
      // 审查 I-2：abort 且无任何内容时同样移除空气泡（原仅错误场景移除）
      if (!assistant.content && (streamError.value || wasAborted)) {
        removeAssistant?.(assistant)
      }
      scrollToBottom?.()
    }
  }

  /** 用户主动中断：推进代际（I-2）并中止 SSE。 */
  function abort() {
    streamSeq += 1 // 审查 I-2：中断后旧流在途轮询不再写缓冲
    chatAbort?.()
  }

  /** 卸载清理（审查 N-3/N-13）：中止进行中的流与历史轮询定时器。 */
  function dispose() {
    streamSeq += 1 // 审查 I-2：卸载后在途轮询不再写缓冲
    chatAbort?.()
    stopPolling()
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
    if (flushTimer != null) {
      clearTimeout(flushTimer)
      flushTimer = null
    }
  }

  return { streaming, streamError, stream, abort, dispose }
}