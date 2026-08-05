import type { ChatMessageItem, ChatStreamEvent } from '@/types'
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
  const controller = new AbortController()
  const promise = (async () => {
    const resp = await fetch(`/api/books/${bookId}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
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
  })()
  return { promise, abort: () => controller.abort() }
}