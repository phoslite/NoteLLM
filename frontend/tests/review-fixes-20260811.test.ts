/**
 * 2026-08-11 四域复审 C 域回归测试（docs/审查报告-20260811-四域复审.md §3）：
 * - C-I1：switchMode 清空旧模式池消息，四能力池不串台；
 * - C-I2：流式中刷新历史按 stream_key 排除在途 DB 行，不再出现「半截+完整」重复；
 * - C-I4：任务中心「最近 N 条已完成」按 created_at 降序取最新；
 * - 共享合并工具 mergeChatHistory / latestFinishedTasks 单测。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, ref } from 'vue'

const mocks = vi.hoisted(() => ({
  listGlobalChatMessages: vi.fn(),
  clearGlobalChatMessages: vi.fn(async () => null),
  deleteGlobalChatSession: vi.fn(async () => null),
  streamGlobalChat: vi.fn(),
  listChatMessages: vi.fn(),
  clearChatMessages: vi.fn(async () => null),
  streamChat: vi.fn(),
}))

vi.mock('@/api/chat', () => ({
  listGlobalChatMessages: mocks.listGlobalChatMessages,
  clearGlobalChatMessages: mocks.clearGlobalChatMessages,
  deleteGlobalChatSession: mocks.deleteGlobalChatSession,
  streamGlobalChat: mocks.streamGlobalChat,
  listChatMessages: mocks.listChatMessages,
  clearChatMessages: mocks.clearChatMessages,
  streamChat: mocks.streamChat,
}))

import { useGlobalAi } from '../src/composables/useGlobalAi'
import { useReaderAi } from '../src/composables/useReaderAi'
import { mergeChatHistory } from '../src/utils/chatMerge'
import { latestFinishedTasks } from '../src/utils/task'
import type { ChatMessageItem, TaskItem } from '../src/types'

function msg(partial: Partial<ChatMessageItem>): ChatMessageItem {
  return {
    id: 0, role: 'user', content: '', stream_key: null,
    book_id: null, chapter_id: null, ref_para_pos: null, created_at: null,
    ...partial,
  }
}

function task(partial: Partial<TaskItem>): TaskItem {
  return {
    id: 't', type: 'text', name: 'n', status: 'queued', progress: 0, stage: '',
    result: null, error: null, related_id: null, created_at: null, finished_at: null,
    ...partial,
  }
}

function controllableStream() {
  let onEvent: ((ev: Record<string, unknown>) => void) | null = null
  let resolvePromise!: () => void
  const promise = new Promise<void>((resolve) => { resolvePromise = resolve })
  return {
    promise,
    abort: vi.fn(),
    setHandler: (fn: (ev: Record<string, unknown>) => void) => { onEvent = fn },
    emit: (ev: Record<string, unknown>) => onEvent?.(ev),
    resolve: () => resolvePromise(),
  }
}

beforeEach(() => {
  vi.resetAllMocks()
  mocks.listGlobalChatMessages.mockResolvedValue([])
  mocks.listChatMessages.mockResolvedValue([])
  mocks.clearGlobalChatMessages.mockResolvedValue(null)
  mocks.deleteGlobalChatSession.mockResolvedValue(null)
  mocks.clearChatMessages.mockResolvedValue(null)
  ;(globalThis as Record<string, unknown>).window = { getSelection: () => null }
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('mergeChatHistory（C-I2 共享合并工具）', () => {
  it('在途流：DB 同 stream_key 部分行被排除，本地气泡唯一展示', () => {
    const local = [
      msg({ id: 1, role: 'user', content: '问题', local: true }),
      msg({ id: 2, role: 'assistant', content: '部分回复', local: true, stream_key: 'k1' }),
    ]
    const rows = [
      msg({ id: 9, role: 'user', content: '问题' }),
      msg({ id: 10, role: 'assistant', content: '部分回复', stream_key: 'k1' }),
    ]
    const merged = mergeChatHistory(local, rows)
    // DB 中同 stream_key 的行被排除（否则折叠再展开出现半截+完整重复）
    expect(merged.map((m) => m.id)).toEqual([9, 1, 2])
  })

  it('历史行为兼容：已落库行按角色+内容去重，本地新增消息保留', () => {
    const local = [msg({ id: 1, role: 'user', content: '本地新问', local: true })]
    const rows = [msg({ id: 5, role: 'assistant', content: '历史回答' })]
    const merged = mergeChatHistory(local, rows)
    expect(merged.map((m) => m.content)).toEqual(['历史回答', '本地新问'])
  })

  it('本地为空时整体替换为历史行', () => {
    const rows = [msg({ id: 5, role: 'assistant', content: '历史回答' })]
    expect(mergeChatHistory([], rows)).toEqual(rows)
  })
})

describe('C-I1 · 切换会话模式清空旧池消息（useReaderAi）', () => {
  it('switchMode 后只保留新模式历史，旧模式本地消息不串台', async () => {
    mocks.listChatMessages.mockImplementation(async (_bookId: number, mode?: string) =>
      mode === '思考逻辑'
        ? [msg({ id: 9, role: 'assistant', content: '思考逻辑历史' })]
        : [],
    )
    const ai = useReaderAi({
      bookId: ref(1),
      currentChapterId: ref(10),
      currentChapter: computed(() => ({ id: 10, index: 1, title: '第一章', content_text: '' }) as never),
      scrollEl: ref(null),
      takeSelection: () => '',
      openMindmap: vi.fn(),
      scrollChat: vi.fn(),
    })
    // 模拟默认池中已有的本地消息（旧缺陷：会被合并进新模式历史尾部）
    ai.chatMessages.value = [msg({ id: 1, role: 'user', content: '旧模式问题', local: true })]
    await ai.switchMode('思考逻辑')
    const contents = ai.chatMessages.value.map((m) => m.content)
    expect(contents).toEqual(['思考逻辑历史'])
    expect(contents).not.toContain('旧模式问题')

    // 切回默认池：加载空历史，旧消息不再累积
    await ai.switchMode('')
    expect(ai.chatMessages.value).toEqual([])
  })
})

describe('C-I2 · 流式中刷新历史不重复（useGlobalAi）', () => {
  it('DB 已落库同 stream_key 部分行时，刷新后仍只有一条 assistant 气泡', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] })
    vi.stubGlobal('crypto', { randomUUID: () => 'gkey-1' })

    const stream = controllableStream()
    mocks.streamGlobalChat.mockImplementation((_params: unknown, onEvent: (ev: Record<string, unknown>) => void) => {
      stream.setHandler(onEvent)
      return stream
    })
    mocks.listGlobalChatMessages.mockResolvedValueOnce([]) // 创建时 loadHistory

    const ai = useGlobalAi()
    ai.input.value = 'hi'
    const sendPromise = ai.send()
    stream.emit({ type: 'delta', text: '部分' })
    await vi.advanceTimersByTimeAsync(80) // flush → assistant.content='部分'

    // 模拟面板折叠再展开：后端滚动落库了同 stream_key 的部分行
    mocks.listGlobalChatMessages.mockResolvedValueOnce([
      msg({ id: 5, role: 'assistant', content: '部分', stream_key: 'gkey-1' }),
    ])
    await ai.refreshHistory()

    const assistants = ai.messages.value.filter((m) => m.role === 'assistant')
    expect(assistants.length).toBe(1) // 修复前：本地半截 + DB 半截同时显示 → 2 条
    expect(assistants[0].content).toBe('部分')

    stream.emit({ type: 'end', text: '部分回复完成', citations: [], cached: false })
    stream.resolve()
    await sendPromise
  })
})

describe('C-I4 · 任务中心最近完成顺序（latestFinishedTasks）', () => {
  it('按 created_at 降序取最近 3 条终态任务（最新在前）', () => {
    const all: TaskItem[] = [
      task({ id: 'a', status: 'running', created_at: '2026-08-11T10:00:00Z' }),
      task({ id: 'b', status: 'success', created_at: '2026-08-11T09:00:00Z' }),
      task({ id: 'c', status: 'failed', created_at: '2026-08-11T11:00:00Z' }),
      task({ id: 'd', status: 'success', created_at: '2026-08-11T08:00:00Z' }),
    ]
    expect(latestFinishedTasks(all, 3).map((t) => t.id)).toEqual(['c', 'b', 'd'])
  })

  it('终态不足 3 条时全量返回；运行中任务不进入列表', () => {
    const all: TaskItem[] = [
      task({ id: 'a', status: 'success', created_at: '2026-08-11T09:00:00Z' }),
      task({ id: 'b', status: 'queued', created_at: '2026-08-11T10:00:00Z' }),
    ]
    expect(latestFinishedTasks(all, 3).map((t) => t.id)).toEqual(['a'])
  })
})
