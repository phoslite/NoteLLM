import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, ref } from 'vue'

/**
 * F1/F2 回归测试（docs/审查报告-20260810.md §2.1）：
 * - F1：全局 AI 点「停止」后 AbortError 分支未复位 streaming / 未清轮询定时器 → 永久卡死；
 * - F2：SSE 正常收尾但无终态事件（end/error）→ streaming 卡 true。
 * 修复后两种场景都必须复位 streaming、清理轮询定时器，且再次发送可用。
 */
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

vi.mock('element-plus', () => ({
  ElMessage: { error: vi.fn(), success: vi.fn(), warning: vi.fn() },
}))

import { useGlobalAi } from '../src/composables/useGlobalAi'
import { useReaderAi } from '../src/composables/useReaderAi'

/** 可控的流：abort() 以 AbortError 拒绝（模拟用户点「停止」）；resolve() 模拟 SSE 正常收尾。 */
function deferredStream() {
  let resolvePromise!: () => void
  let rejectPromise!: (err: unknown) => void
  const promise = new Promise<void>((resolve, reject) => {
    resolvePromise = resolve
    rejectPromise = reject
  })
  const abort = vi.fn(() => rejectPromise(new DOMException('The user aborted a request.', 'AbortError')))
  return { promise, abort, resolve: resolvePromise, reject: rejectPromise }
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.clearAllMocks()
  mocks.listGlobalChatMessages.mockResolvedValue([])
  mocks.listChatMessages.mockResolvedValue([])
  // sendChat 内部会调 currentSelection() → window.getSelection()（Node 环境无 window）
  ;(globalThis as Record<string, unknown>).window = { getSelection: () => null }
})

afterEach(() => {
  vi.useRealTimers()
})

describe('F1 · 全局 AI 点「停止」不再卡死（useGlobalAi）', () => {
  it('abort 后复位 streaming、清轮询定时器、不弹错误，且可再次发送', async () => {
    const stream = deferredStream()
    mocks.streamGlobalChat.mockReturnValueOnce(stream)

    const ai = useGlobalAi()
    ai.input.value = '你好'
    const sendPromise = ai.send()
    expect(ai.streaming.value).toBe(true)

    ai.abort() // 用户点「停止」→ AbortError
    await sendPromise

    expect(ai.streaming.value).toBe(false)
    expect(ai.streamError.value).toBe('') // 主动中断不显示错误横幅
    // 轮询定时器已清理：超过轮询周期（2000ms）不再拉取历史
    const baseline = mocks.listGlobalChatMessages.mock.calls.length
    await vi.advanceTimersByTimeAsync(2100)
    expect(mocks.listGlobalChatMessages.mock.calls.length).toBe(baseline)

    // 卡死症状是 streaming 卡 true 导致 send 直接 return；能再次发送即证明已复位
    const stream2 = deferredStream()
    mocks.streamGlobalChat.mockReturnValueOnce(stream2)
    ai.input.value = '再问一次'
    const second = ai.send()
    expect(ai.streaming.value).toBe(true)
    expect(ai.messages.value.filter((m) => m.role === 'user')).toHaveLength(2)
    stream2.resolve()
    await second
    expect(ai.streaming.value).toBe(false)
  })
})

describe('F2 · SSE 无终态事件时不再卡 streaming', () => {
  it('全局 AI：promise 正常结束但无 end/error → 复位 streaming 并清轮询定时器', async () => {
    const stream = deferredStream()
    mocks.streamGlobalChat.mockReturnValueOnce(stream)

    const ai = useGlobalAi()
    ai.input.value = '你好'
    const sendPromise = ai.send()
    expect(ai.streaming.value).toBe(true)

    stream.resolve() // 连接结束，但从未收到 end/error 终态
    await sendPromise

    expect(ai.streaming.value).toBe(false)
    expect(ai.streamError.value).toBe('')
    const baseline = mocks.listGlobalChatMessages.mock.calls.length
    await vi.advanceTimersByTimeAsync(2100)
    expect(mocks.listGlobalChatMessages.mock.calls.length).toBe(baseline)
  })

  it('阅读页 AI：promise 正常结束但无 end/error → 复位 streaming 并回调 onAssistantDone', async () => {
    const stream = deferredStream()
    mocks.streamChat.mockReturnValueOnce(stream)
    const onAssistantDone = vi.fn()
    const ai = useReaderAi({
      bookId: ref(1),
      currentChapterId: ref(10),
      currentChapter: computed(() => undefined),
      scrollEl: ref(null),
      takeSelection: () => '',
      openMindmap: vi.fn(),
      scrollChat: vi.fn(),
      onAssistantDone,
    })

    ai.aiInput.value = '解读本章'
    const sendPromise = ai.sendChat()
    expect(ai.streaming.value).toBe(true)

    stream.resolve()
    await sendPromise

    expect(ai.streaming.value).toBe(false)
    expect(ai.streamError.value).toBe('')
    expect(onAssistantDone).toHaveBeenCalledTimes(1)
    const baseline = mocks.listChatMessages.mock.calls.length
    await vi.advanceTimersByTimeAsync(2100)
    expect(mocks.listChatMessages.mock.calls.length).toBe(baseline)
  })
})

describe('F1 · 阅读页 AI 中断后复位（useReaderAi）', () => {
  it('abort 后复位 streaming、不弹错误、不回调完成', async () => {
    const stream = deferredStream()
    mocks.streamChat.mockReturnValueOnce(stream)
    const onAssistantDone = vi.fn()
    const ai = useReaderAi({
      bookId: ref(1),
      currentChapterId: ref(10),
      currentChapter: computed(() => undefined),
      scrollEl: ref(null),
      takeSelection: () => '',
      openMindmap: vi.fn(),
      scrollChat: vi.fn(),
      onAssistantDone,
    })

    ai.aiInput.value = '解读本章'
    const sendPromise = ai.sendChat()
    expect(ai.streaming.value).toBe(true)

    ai.abortChat()
    await sendPromise

    expect(ai.streaming.value).toBe(false)
    expect(ai.streamError.value).toBe('') // 主动中断不显示误导性错误横幅
    expect(onAssistantDone).not.toHaveBeenCalled()
  })
})
