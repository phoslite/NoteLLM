import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import { useStreamSession, type StreamAssistant } from '../src/composables/useStreamSession'
import type { ChatMessageItem, ChatStreamEvent } from '../src/types'

/**
 * MO3 内核级行为契约测试（第 6 轮）：直接以 mock 注入 fetchStream/pollHistory 驱动内核，
 * 覆盖 F1/F2/MO2 六分支/I-2/I-4/I-13/C-1 语义（与 useReaderAi/useGlobalAi 既有契约测试
 * 同一行为面，断言语义等价）。时间轴依赖与既有契约测试一致（fake timers + faked Date）。
 */

/** 可控流：emit 手动发 SSE 事件；resolve() 正常收尾；abort() 以 AbortError 拒绝。 */
function controllableStream() {
  let onEvent: ((ev: ChatStreamEvent) => void) | null = null
  let resolvePromise!: () => void
  let rejectPromise!: (err: unknown) => void
  const promise = new Promise<void>((resolve, reject) => {
    resolvePromise = resolve
    rejectPromise = reject
  })
  return {
    promise,
    abort: vi.fn(() => rejectPromise(new DOMException('The user aborted a request.', 'AbortError'))),
    setHandler: (fn: (ev: ChatStreamEvent) => void) => { onEvent = fn },
    emit: (ev: ChatStreamEvent) => onEvent?.(ev),
    resolve: () => resolvePromise(),
    reject: (err: unknown) => rejectPromise(err),
  }
}

function makeSession(overrides: Partial<Parameters<typeof useStreamSession>[0]> = {}) {
  const pollHistory = vi.fn(async () => [])
  const hooks = {
    onFinal: vi.fn(),
    onDelta: vi.fn(),
    onError: vi.fn(),
    scrollToBottom: vi.fn(),
    removeAssistant: vi.fn(),
  }
  const session = useStreamSession({
    fetchStream: vi.fn(),
    pollHistory,
    ...hooks,
    ...overrides,
  })
  return { session, pollHistory, hooks }
}

function makeAssistant(overrides: Partial<StreamAssistant> = {}): StreamAssistant {
  return reactive<StreamAssistant>({
    id: 1, role: 'assistant', content: '', local: true,
    book_id: null, chapter_id: null, ref_para_pos: null, created_at: null,
    ...overrides,
  })
}

function row(streamKey: string, content: string, overrides: Partial<ChatMessageItem> = {}): ChatMessageItem {
  return { id: 9, role: 'assistant', content, stream_key: streamKey, book_id: null, chapter_id: null, ref_para_pos: null, created_at: null, ...overrides }
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] })
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('F1 · 停止复位（内核）', () => {
  it('abort 后 streaming/streamError 复位、轮询停止、可再次发送', async () => {
    const stream = controllableStream()
    const { session, pollHistory } = makeSession({
      fetchStream: (onEvent) => { stream.setHandler(onEvent); return stream },
    })

    const a1 = makeAssistant()
    const p1 = session.stream(a1, 'k-1')
    expect(session.streaming.value).toBe(true)
    session.abort()
    await p1

    expect(session.streaming.value).toBe(false)
    expect(session.streamError.value).toBe('') // 主动中断不显示错误横幅
    const baseline = pollHistory.mock.calls.length
    await vi.advanceTimersByTimeAsync(2100) // 轮询定时器已清理
    expect(pollHistory.mock.calls.length).toBe(baseline)

    // 再次发送可用
    const stream2 = controllableStream()
    const { session: s2, pollHistory: ph2 } = makeSession({
      fetchStream: (onEvent) => { stream2.setHandler(onEvent); return stream2 },
    })
    const a2 = makeAssistant({ id: 3 })
    const p2 = s2.stream(a2, 'k-2')
    expect(s2.streaming.value).toBe(true)
    stream2.emit({ type: 'delta', text: 'hi' })
    await vi.advanceTimersByTimeAsync(80)
    expect(a2.content).toBe('hi')
    stream2.emit({ type: 'end', text: 'hi', citations: [], cached: false })
    stream2.resolve()
    await p2
    expect(ph2).toBeDefined()
  })

  it('fetchStream 同步抛错 → streaming 复位、streamError/onError 设置、不启动轮询、移除空气泡', async () => {
    const { session, pollHistory, hooks } = makeSession({
      fetchStream: () => {
        throw new Error('sendParams 快照缺失')
      },
    })
    const a1 = makeAssistant()
    await session.stream(a1, 'k-1')

    expect(session.streaming.value).toBe(false) // 第 7 轮 F1：不再永久卡 true
    expect(session.streamError.value).toBe('sendParams 快照缺失')
    expect(hooks.onError).toHaveBeenCalledWith('sendParams 快照缺失')
    expect(hooks.removeAssistant).toHaveBeenCalledWith(a1) // 空内容空气泡移除（与错误路径一致）
    const baseline = pollHistory.mock.calls.length
    await vi.advanceTimersByTimeAsync(2100)
    expect(pollHistory.mock.calls.length).toBe(baseline) // 同步抛错未启动轮询
  })
})

describe('F2 · 无终态复位（内核）', () => {
  it('promise 正常结束但无 end/error → 复位 streaming、清轮询、onFinal 回调', async () => {
    const stream = controllableStream()
    const { session, pollHistory, hooks } = makeSession({
      fetchStream: (onEvent) => { stream.setHandler(onEvent); return stream },
    })
    const a = makeAssistant()
    const p = session.stream(a, 'k-1')
    expect(session.streaming.value).toBe(true)

    stream.resolve()
    await p

    expect(session.streaming.value).toBe(false)
    expect(session.streamError.value).toBe('')
    expect(hooks.onFinal).toHaveBeenCalledTimes(1) // 对应 reader onAssistantDone
    const baseline = pollHistory.mock.calls.length
    await vi.advanceTimersByTimeAsync(2100)
    expect(pollHistory.mock.calls.length).toBe(baseline)
  })

  it('abort 后的 F2 兜底不回调 onFinal（对应 reader 中断不计数未读）', async () => {
    const stream = controllableStream()
    const { session, hooks } = makeSession({
      fetchStream: (onEvent) => { stream.setHandler(onEvent); return stream },
    })
    const a = makeAssistant()
    const p = session.stream(a, 'k-1')
    session.abort()
    await p
    expect(session.streaming.value).toBe(false)
    expect(hooks.onFinal).not.toHaveBeenCalled()
  })
})

describe('MO2 · 六个终态分支（end/error/catch/F2/dispose/abortChat）', () => {
  it('end 终态：内容终态写入、streaming 复位、轮询停止、onFinal 回调', async () => {
    const stream = controllableStream()
    const { session, pollHistory, hooks } = makeSession({
      fetchStream: (onEvent) => { stream.setHandler(onEvent); return stream },
    })
    const a = makeAssistant()
    const p = session.stream(a, 'k-1')
    stream.emit({ type: 'delta', text: 'hello' })
    await vi.advanceTimersByTimeAsync(80)
    stream.emit({ type: 'end', text: 'hello', citations: [], cached: true })
    stream.resolve()
    await p
    expect(a.content).toBe('hello')
    expect(a.cached).toBe(true)
    expect(a.local).toBe(false)
    expect(session.streaming.value).toBe(false)
    expect(hooks.onFinal).toHaveBeenCalledTimes(1)
    const baseline = pollHistory.mock.calls.length
    await vi.advanceTimersByTimeAsync(2100)
    expect(pollHistory.mock.calls.length).toBe(baseline) // end 已停轮询
  })

  it('error 事件终态：streamError/onError 设置、streaming 复位、轮询停止', async () => {
    const stream = controllableStream()
    const { session, pollHistory, hooks } = makeSession({
      fetchStream: (onEvent) => { stream.setHandler(onEvent); return stream },
    })
    const a = makeAssistant()
    const p = session.stream(a, 'k-1')
    stream.emit({ type: 'error', message: '服务端错误' })
    stream.resolve()
    await p
    expect(session.streaming.value).toBe(false)
    expect(session.streamError.value).toBe('服务端错误')
    expect(hooks.onError).toHaveBeenCalledWith('服务端错误')
    const baseline = pollHistory.mock.calls.length
    await vi.advanceTimersByTimeAsync(2100)
    expect(pollHistory.mock.calls.length).toBe(baseline)
  })

  it('catch 分支（非 abort）：streamError/onError 设置、streaming 复位、轮询停止', async () => {
    const stream = controllableStream()
    const { session, pollHistory, hooks } = makeSession({
      fetchStream: (onEvent) => { stream.setHandler(onEvent); return stream },
    })
    const a = makeAssistant()
    const p = session.stream(a, 'k-1')
    stream.reject(new Error('连接中断'))
    await p
    expect(session.streaming.value).toBe(false)
    expect(session.streamError.value).toBe('连接中断')
    expect(hooks.onError).toHaveBeenCalledWith('连接中断')
    const baseline = pollHistory.mock.calls.length
    await vi.advanceTimersByTimeAsync(2100)
    expect(pollHistory.mock.calls.length).toBe(baseline)
  })

  it('dispose 后在途轮询不再触发新调用、streaming 复位（N-3/N-13）', async () => {
    let releasePoll!: (v: unknown) => void
    const pollGate = new Promise((resolve) => { releasePoll = resolve })
    const pollHistory = vi.fn().mockImplementationOnce(() => pollGate)
    const stream = controllableStream()
    const { session } = makeSession({ fetchStream: (onEvent) => { stream.setHandler(onEvent); return stream }, pollHistory })
    const a = makeAssistant()
    const p = session.stream(a, 'k-1')
    await vi.advanceTimersByTimeAsync(2000) // 轮询挂起中
    session.dispose()
    await p
    expect(session.streaming.value).toBe(false)
    releasePoll([row('k-1', 'late')])
    await Promise.resolve()
    const baseline = pollHistory.mock.calls.length
    await vi.advanceTimersByTimeAsync(2100)
    expect(pollHistory.mock.calls.length).toBe(baseline) // dispose 后不再有新轮询
  })
})

describe('I-13d · abort 后在途轮询不污染新流（C-1 清旧池，内核级）', () => {
  it('旧流轮询迟到响应不污染新流内容', async () => {
    let releaseOldPoll!: (v: unknown) => void
    const oldPollPromise = new Promise((resolve) => { releaseOldPoll = resolve })
    const pollHistory = vi.fn().mockImplementationOnce(() => oldPollPromise)

    let reject1!: (err: unknown) => void
    const p1p = new Promise<void>((_resolve, reject) => { reject1 = reject })
    const stream1 = {
      promise: p1p,
      abort: vi.fn(() => reject1(new DOMException('The user aborted a request.', 'AbortError'))),
      setHandler: vi.fn(),
    }
    let onEvent2: ((ev: ChatStreamEvent) => void) | null = null
    let resolve2!: () => void
    const p2p = new Promise<void>((resolve) => { resolve2 = resolve })
    const stream2 = {
      promise: p2p,
      abort: vi.fn(),
      setHandler: (fn: (ev: ChatStreamEvent) => void) => { onEvent2 = fn },
    }
    const { session } = makeSession({
      pollHistory,
      fetchStream: vi.fn()
        .mockImplementationOnce((onEvent: (ev: ChatStreamEvent) => void) => { stream1.setHandler(onEvent); return stream1 })
        .mockImplementationOnce((onEvent: (ev: ChatStreamEvent) => void) => { stream2.setHandler(onEvent); return stream2 }),
    })

    const a1 = makeAssistant({ id: 1 })
    const sp1 = session.stream(a1, 'k-1')
    await vi.advanceTimersByTimeAsync(2000) // 流1轮询触发（挂起）
    session.abort()
    await sp1

    const a2 = makeAssistant({ id: 2 })
    const sp2 = session.stream(a2, 'k-2')
    onEvent2?.({ type: 'delta', text: 'new' })
    await vi.advanceTimersByTimeAsync(80) // flush 'new'
    // 旧流轮询迟到返回（含旧内容）——守卫失效时会写进共享 pendingText 污染新流
    releaseOldPoll([row('k-1', 'oldtail')])
    await Promise.resolve()
    await vi.advanceTimersByTimeAsync(0)
    expect(a2.content).toBe('new')
    onEvent2?.({ type: 'end', text: 'new', citations: [], cached: false })
    resolve2()
    await sp2
    expect(a2.content).toBe('new') // end 覆盖后仍无污染
  })
})

describe('I-2 · SSE 活跃期轮询跳过（防尾部重放重复）', () => {
  it('距最近 SSE 事件 <500ms 的轮询 tick 不拉历史；静默期 tick 正常补差', async () => {
    const stream = controllableStream()
    const pollMock = vi.fn().mockResolvedValueOnce([row('k-1', 'ab')])
    const { session } = makeSession({
      fetchStream: (onEvent) => { stream.setHandler(onEvent); return stream },
      pollHistory: pollMock,
    })
    const a = makeAssistant()
    const p = session.stream(a, 'k-1')
    await vi.advanceTimersByTimeAsync(1550) // t=1550
    stream.emit({ type: 'delta', text: 'a' }) // lastSseActivityAt=1550
    await vi.advanceTimersByTimeAsync(450) // t=2000：2000-1550=450 < 500 → 跳过
    expect(pollMock).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(2000) // t=4000：静默 ≥500ms → 轮询补差
    expect(pollMock).toHaveBeenCalledTimes(1)
    await Promise.resolve()
    await vi.advanceTimersByTimeAsync(80) // flush 差量 'b'
    expect(a.content).toBe('ab')
    stream.emit({ type: 'end', text: 'ab', citations: [], cached: false })
    stream.resolve()
    await p
  })
})

describe('I-13 · 轮询差量前缀对齐（不重复 ab$$x$$x）', () => {
  it('落库内容已含未刷出增量时，flush 后不重复追加', async () => {
    const stream = controllableStream()
    const pollMock = vi.fn().mockResolvedValueOnce([row('k-1', 'ab$$x')])
    const { session } = makeSession({
      fetchStream: (onEvent) => { stream.setHandler(onEvent); return stream },
      pollHistory: pollMock,
    })
    const a = makeAssistant()
    const p = session.stream(a, 'k-1')
    stream.emit({ type: 'delta', text: 'a' })
    await vi.advanceTimersByTimeAsync(80) // flush 'a' → content='a'
    await vi.advanceTimersByTimeAsync(1420) // t=1500
    stream.emit({ type: 'delta', text: 'b' })
    await vi.advanceTimersByTimeAsync(80) // t=1580 flush 'b' → content='ab'
    stream.emit({ type: 'delta', text: '$$x' }) // 未闭合，flush 链推迟
    await vi.advanceTimersByTimeAsync(20) // t=1600
    await vi.advanceTimersByTimeAsync(400) // t=2000：距活动 420ms → 轮询跳过（与既有契约一致）
    expect(pollMock).not.toHaveBeenCalled()
    // flush 链在距 lastFlushAt ≥500ms（t≈2140）时只追加一次
    await vi.advanceTimersByTimeAsync(200)
    expect(a.content).toBe('ab$$x')
    // 静默期轮询（t=4000）补差也不产生 ab$$x$$x
    await vi.advanceTimersByTimeAsync(1800)
    expect(pollMock).toHaveBeenCalledTimes(1)
    await Promise.resolve()
    await vi.advanceTimersByTimeAsync(400)
    expect(a.content).toBe('ab$$x')
    stream.emit({ type: 'end', text: 'ab$$x', citations: [], cached: false })
    stream.resolve()
    await p
  })
})

describe('I-4 · 轮询服务端改写与 DB 落后保护', () => {
  it('服务端改写（本地非前缀）→ 整体覆盖并清 pendingText', async () => {
    const stream = controllableStream()
    const { session } = makeSession({
      fetchStream: (onEvent) => { stream.setHandler(onEvent); return stream },
      pollHistory: vi.fn().mockResolvedValueOnce([row('k-1', 'zzz')]),
    })
    const a = makeAssistant()
    const p = session.stream(a, 'k-1')
    stream.emit({ type: 'delta', text: 'ab' })
    await vi.advanceTimersByTimeAsync(80) // content='ab'
    await vi.advanceTimersByTimeAsync(1920) // t=2000 轮询
    await Promise.resolve()
    expect(a.content).toBe('zzz')
    stream.emit({ type: 'end', text: 'zzz', citations: [], cached: false })
    stream.resolve()
    await p
    expect(a.content).toBe('zzz')
  })

  it('DB 落后于本地缓冲 → 不覆盖本地内容（长度不超即跳过，pendingText 不受影响）', async () => {
    const stream = controllableStream()
    const pollMock = vi.fn().mockResolvedValueOnce([row('k-1', 'ab')])
    const { session } = makeSession({
      fetchStream: (onEvent) => { stream.setHandler(onEvent); return stream },
      pollHistory: pollMock,
    })
    const a = makeAssistant()
    const p = session.stream(a, 'k-1')
    stream.emit({ type: 'delta', text: 'ab' })
    await vi.advanceTimersByTimeAsync(80) // content='ab'
    await vi.advanceTimersByTimeAsync(1420) // t=1500
    stream.emit({ type: 'delta', text: 'b' }) // lastSseActivityAt=1500
    await vi.advanceTimersByTimeAsync(80) // t=1580 flush 'b' → content='abb'
    await vi.advanceTimersByTimeAsync(420) // t=2000 轮询：DB 'ab' 长度 2 < 本地 3 → 跳过不覆盖
    await Promise.resolve()
    expect(a.content).toBe('abb')
    stream.emit({ type: 'end', text: 'abb', citations: [], cached: false })
    stream.resolve()
    await p
    expect(pollMock).toHaveBeenCalledTimes(1)
  })
})

describe('差异点钩子（reader 滚动/空气泡移除/onDelta）', () => {
  it('flush 增量、轮询补差与 finally 触发 scrollToBottom；空气泡移除仅空内容+终态', async () => {
    const stream = controllableStream()
    const scrollToBottom = vi.fn()
    const removeAssistant = vi.fn()
    const onDelta = vi.fn()
    const pollMock = vi.fn().mockResolvedValueOnce([row('k-1', 'ab')])
    const { session } = makeSession({
      fetchStream: (onEvent) => { stream.setHandler(onEvent); return stream },
      scrollToBottom,
      removeAssistant,
      onDelta,
      pollHistory: pollMock,
    })
    const a = makeAssistant()
    const p = session.stream(a, 'k-1')
    stream.emit({ type: 'delta', text: 'a' })
    await vi.advanceTimersByTimeAsync(80) // flush → scroll 一次
    expect(scrollToBottom).toHaveBeenCalledTimes(1)
    expect(onDelta).toHaveBeenCalledWith('a')
    await vi.advanceTimersByTimeAsync(1920) // t=2000 轮询补差 'b' → scroll 一次
    await Promise.resolve()
    await vi.advanceTimersByTimeAsync(80)
    expect(a.content).toBe('ab')
    expect(scrollToBottom.mock.calls.length).toBeGreaterThanOrEqual(2)
    stream.emit({ type: 'end', text: 'ab', citations: [], cached: false })
    stream.resolve()
    await p // finally → scroll 一次
    expect(scrollToBottom).toHaveBeenCalledTimes(4) // flush×2 + 轮询补差 + finally
    expect(removeAssistant).not.toHaveBeenCalled() // 有内容不移除
  })

  it('abort 且无任何内容时移除空气泡', async () => {
    const stream = controllableStream()
    const removeAssistant = vi.fn()
    const { session } = makeSession({
      fetchStream: (onEvent) => { stream.setHandler(onEvent); return stream },
      removeAssistant,
    })
    const a = makeAssistant()
    const p = session.stream(a, 'k-1')
    session.abort()
    await p
    expect(removeAssistant).toHaveBeenCalledWith(a)
  })
})