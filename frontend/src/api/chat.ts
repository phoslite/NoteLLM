import type { ChatMessageItem, ChatStreamEvent } from '@/types'
import { SSE_IDLE_TIMEOUT_MS } from '@/utils/constants'
import { del, get } from './client'

function withMode(url: string, mode: string) {
  return mode ? `${url}?mode=${encodeURIComponent(mode)}` : url
}

/** 读取本书指定会话的对话历史（mode 为空=默认对话；解读/概论/思考逻辑为能力模式分池）。 */
export function listChatMessages(bookId: number, mode = '') {
  return get<ChatMessageItem[]>(withMode(`/books/${bookId}/chat/messages`, mode))
}

export function clearChatMessages(bookId: number, mode = '') {
  return del<null>(withMode(`/books/${bookId}/chat/messages`, mode))
}

/**
 * 空闲超时器（三审 Major-3 修复）：每次 touch() 重置计时，到期中止 signal 并置 fired。
 * 替代原 AbortSignal.timeout(总时长)——长流持续产出 token 超过 2 分钟不再被误杀，
 * 只有「长时间无新数据」（挂起）才会触发兜底。
 */
class IdleTimeout {
  readonly signal: AbortSignal
  fired = false
  private controller = new AbortController()
  private timer: ReturnType<typeof setTimeout> | null = null

  constructor(private readonly ms: number) {
    this.signal = this.controller.signal
    this.arm()
  }

  /** 收到数据时重置计时。 */
  touch() {
    this.arm()
  }

  dispose() {
    if (this.timer !== null) {
      clearTimeout(this.timer)
      this.timer = null
    }
  }

  private arm() {
    this.dispose()
    this.timer = setTimeout(() => {
      this.fired = true
      this.controller.abort()
    }, this.ms)
  }
}

/** SSE 流式读取内核：{ promise, abort }；空闲超时抛友好错误，用户主动 abort 抛 AbortError（调用方静默）。 */
function streamSse(
  url: string,
  body: unknown,
  onEvent: (ev: ChatStreamEvent) => void,
  idleMs = SSE_IDLE_TIMEOUT_MS,
): { promise: Promise<void>; abort: () => void } {
  const controller = new AbortController()
  const promise = (async () => {
    // C-M4 / 三审 Major-3：挂起兜底用「空闲超时」而非总时长——每次收到数据重置 120s
    const idle = new IdleTimeout(idleMs)
    const timeoutMsg = `AI 响应空闲超时（${Math.round(idleMs / 1000)} 秒无新数据），已中断`
    // AbortSignal.any 需 Chrome 116+；旧内核降级：idle 触发时反向桥接中断 fetch
    // （否则 reader.read() 永久 pending，循环内 fired 检查不可达，空闲超时形同虚设——四轮 M1）
    const signal = typeof AbortSignal.any === 'function' ? AbortSignal.any([controller.signal, idle.signal]) : controller.signal
    if (typeof AbortSignal.any !== 'function') {
      idle.signal.addEventListener('abort', () => controller.abort(), { once: true })
    }
    try {
      const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal,
      })
      if (!resp.ok) {
        let msg = `请求失败（${resp.status}）`
        try {
          const data = await resp.json()
          if (data?.detail) msg = data.detail
        } catch {
          /* 非 JSON 错误体时保留默认信息 */
        }
        throw new Error(msg)
      }
      if (!resp.body) throw new Error('浏览器不支持流式响应')
      const reader = resp.body.getReader()
      const decoder = new TextDecoder('utf-8')
      let buf = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        idle.touch()
        if (idle.fired) throw new Error(timeoutMsg) // 旧内核无 AbortSignal.any 时的兜底检查
        buf += decoder.decode(value, { stream: true })
        const parts = buf.split('\n\n')
        buf = parts.pop() ?? ''
        for (const part of parts) {
          for (const line of part.split('\n')) {
            if (!line.startsWith('data:')) continue
            const raw = line.slice(5).trim()
            if (!raw) continue
            try {
              onEvent(JSON.parse(raw) as ChatStreamEvent)
            } catch {
              /* 忽略无法解析的事件 */
            }
          }
        }
      }
    } catch (err) {
      if (idle.fired) throw new Error(timeoutMsg)
      throw err
    } finally {
      idle.dispose()
    }
  })()
  return { promise, abort: () => controller.abort() }
}

/** 流式对话（SSE）：逐块回调事件；返回 { promise, abort } 支持中断。 */
export function streamChat(
  bookId: number,
  body: {
    question: string
    chapter_id?: number | null
    selection?: string
    crop_image?: string | null
    crop_label?: string | null
    mode?: string | null
    session_id?: string | null
    /** 方案2 流式滚动落库键（前端生成）：流中增量持久化后按此键轮询历史。 */
    stream_key?: string | null
  },
  onEvent: (ev: ChatStreamEvent) => void,
) {
  return streamSse(`/api/books/${bookId}/chat`, body, onEvent)
}

/* ---------- 决策 37：主页全局 AI 对话（不绑定书籍/章节） ---------- */

/** 读取全局对话历史（session_id 为前端打开面板时生成）。 */
export function listGlobalChatMessages(sessionId: string) {
  return get<ChatMessageItem[]>(`/ai/chat/messages?session_id=${encodeURIComponent(sessionId)}`)
}

export function clearGlobalChatMessages(sessionId: string) {
  return del<null>(`/ai/chat/messages?session_id=${encodeURIComponent(sessionId)}`)
}

/** 删除主页全局会话：清空历史 + 清除该会话的挑选缓存（需求 v1.73）。 */
export function deleteGlobalChatSession(sessionId: string) {
  return del<null>(`/ai/chat/session?session_id=${encodeURIComponent(sessionId)}`)
}

/** 全局对话流式（SSE）：事件回调同 streamChat；返回 { promise, abort }。 */
export function streamGlobalChat(
  body: {
    question: string
    session_id?: string | null
    stream_key?: string | null
  },
  onEvent: (ev: ChatStreamEvent) => void,
) {
  return streamSse('/api/ai/chat', body, onEvent)
}