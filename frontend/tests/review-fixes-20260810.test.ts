import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, ref } from 'vue'

/**
 * 终审复核回归测试（docs/审查报告-20260810-终审.md §6.5 修复项）：
 * - I-10：划词菜单按实际渲染宽度钳制，右侧不出屏（F11）；
 * - I-13：轮询补增量与 pendingText 前缀对齐，不再重复文本（ab$$x$$x）；
 * - I-14：脑图请求序号守卫，旧章节迟到响应不再覆盖新结果；
 * - I-15：页缓存重建入口防重守卫（按钮 loading 之外的第二道防线）。
 */

const mocks = vi.hoisted(() => ({
  listGlobalChatMessages: vi.fn(),
  clearGlobalChatMessages: vi.fn(async () => null),
  deleteGlobalChatSession: vi.fn(async () => null),
  streamGlobalChat: vi.fn(),
  listChatMessages: vi.fn(),
  clearChatMessages: vi.fn(async () => null),
  streamChat: vi.fn(),
  generateMindmap: vi.fn(),
  getPageTextStatus: vi.fn(async () => ({ total: 2, cached: 0 })),
  getPageTextTask: vi.fn(async () => ({ status: 'running' })),
  rebuildPageText: vi.fn(async () => ({ task_id: 't-1' })),
  reextractPage: vi.fn(async () => null),
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

vi.mock('@/api/mindmap', () => ({ generateMindmap: mocks.generateMindmap }))

vi.mock('@/api/vision', () => ({
  getPageTextStatus: mocks.getPageTextStatus,
  getPageTextTask: mocks.getPageTextTask,
  rebuildPageText: mocks.rebuildPageText,
  reextractPage: mocks.reextractPage,
}))

const elError = vi.hoisted(() => vi.fn())
const elSuccess = vi.hoisted(() => vi.fn())
vi.mock('element-plus', () => ({
  ElMessage: { error: elError, success: elSuccess, warning: vi.fn() },
  ElMessageBox: { confirm: vi.fn(async () => true) },
}))

import { useGlobalAi } from '../src/composables/useGlobalAi'
import { useReaderAi } from '../src/composables/useReaderAi'
import { useReaderMindmap } from '../src/composables/useReaderMindmap'
import { useReaderPageCache } from '../src/composables/useReaderPageCache'
import { useReaderSelection } from '../src/composables/useReaderSelection'
import { viewportTopPara } from '../src/utils/viewport'

/** 可控流：可手动 emit SSE 事件；resolve() 模拟连接结束。 */
function controllableStream() {
  let onEvent: ((ev: Record<string, unknown>) => void) | null = null
  let resolvePromise!: () => void
  const promise = new Promise<void>((resolve) => {
    resolvePromise = resolve
  })
  return {
    promise,
    abort: vi.fn(),
    setHandler: (fn: (ev: Record<string, unknown>) => void) => {
      onEvent = fn
    },
    emit: (ev: Record<string, unknown>) => onEvent?.(ev),
    resolve: () => resolvePromise(),
  }
}

beforeEach(() => {
  // 审查 I-2：SSE 活跃守卫会跳过轮询的 mock 调用，未消费的 mockResolvedValueOnce 队列
  // 会跨测试泄漏（I-13b 曾误用 I-13a 的旧行）——统一 resetAllMocks 后重建默认实现
  vi.resetAllMocks()
  mocks.listGlobalChatMessages.mockResolvedValue([])
  mocks.listChatMessages.mockResolvedValue([])
  mocks.getPageTextStatus.mockResolvedValue({ total: 2, cached: 0 })
  mocks.getPageTextTask.mockResolvedValue({ status: 'running' })
  mocks.rebuildPageText.mockResolvedValue({ task_id: 't-1' })
  mocks.reextractPage.mockResolvedValue(null)
  mocks.clearGlobalChatMessages.mockResolvedValue(null)
  mocks.deleteGlobalChatSession.mockResolvedValue(null)
  mocks.clearChatMessages.mockResolvedValue(null)
  ;(globalThis as Record<string, unknown>).window = { getSelection: () => null }
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('I-13 · 轮询不再重复文本（useGlobalAi）', () => {
  it('落库内容已含未刷出增量时，flush 后不出现 ab$$x$$x', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] })
    vi.stubGlobal('crypto', { randomUUID: () => 'key-1' })

    const stream = controllableStream()
    mocks.streamGlobalChat.mockImplementation((_params: unknown, onEvent: (ev: Record<string, unknown>) => void) => {
      stream.setHandler(onEvent)
      return stream
    })
    // 调用#1 = 创建时 loadHistory（空）；调用#2 = t=2000 轮询（落库已含全部 SSE 内容）
    mocks.listGlobalChatMessages
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([
        { id: 1, role: 'assistant', stream_key: 'key-1', content: 'ab$$x', book_id: null, chapter_id: null, ref_para_pos: null, created_at: null },
      ])

    const ai = useGlobalAi()
    ai.input.value = 'hi'
    const sendPromise = ai.send()
    stream.emit({ type: 'delta', text: 'a' })
    await vi.advanceTimersByTimeAsync(80) // flush 'a' → content='a'，lastFlushAt=80
    await vi.advanceTimersByTimeAsync(1420) // t=1500
    stream.emit({ type: 'delta', text: 'b' })
    await vi.advanceTimersByTimeAsync(80) // t=1580 flush 'b' → content='ab'，lastFlushAt=1580
    stream.emit({ type: 'delta', text: '$$x' }) // 未闭合，flush 链推迟
    await vi.advanceTimersByTimeAsync(20) // t=1600

    // t=2000 轮询触发：落库 content='ab$$x'（含未刷出的 '$$x'）
    await vi.advanceTimersByTimeAsync(400)
    const assistant = ai.messages.value.find((m) => m.role === 'assistant')!
    expect(assistant.content).toBe('ab') // 修复：轮询不整体覆盖（pendingText 保留）

    // flush 链每次 80ms 重排，直到距 lastFlushAt ≥500ms（t≈2140）→ 只追加一次
    await vi.advanceTimersByTimeAsync(200)
    expect(assistant.content).toBe('ab$$x')

    stream.emit({ type: 'end', text: 'ab$$x', citations: [], cached: false })
    stream.resolve()
    await sendPromise
  })
})

describe('I-14 · 脑图迟到响应不覆盖新章节（useReaderMindmap）', () => {
  it('旧请求后到但已发起新请求 → mindmapData 保留新结果', async () => {
    let releaseOld!: (v: unknown) => void
    const oldPromise = new Promise((resolve) => {
      releaseOld = resolve
    })
    mocks.generateMindmap
      .mockReturnValueOnce(oldPromise) // 第一次请求（挂起）
      .mockResolvedValueOnce({ title: '新章节脑图', nodes: [{ id: 'n-new' }] }) // 第二次请求（立即完成）

    const ai = useReaderMindmap({
      bookId: ref(1),
      currentChapterId: ref(10),
      chapters: computed(() => []),
      scrollEl: ref(null),
      closeSelection: vi.fn(),
      loadChapter: vi.fn(),
    })
    const first = ai.openMindmap() // 挂起中
    await ai.openMindmap() // 第二次完成 → mindmapData = 新
    expect(ai.mindmapData.value).toEqual({ title: '新章节脑图', nodes: [{ id: 'n-new' }] })

    releaseOld({ title: '旧章节脑图', nodes: [{ id: 'n-old' }] }) // 旧响应迟到
    await first
    await Promise.resolve()
    expect(ai.mindmapData.value).toEqual({ title: '新章节脑图', nodes: [{ id: 'n-new' }] }) // 未被旧响应覆盖
    expect(ai.mindmapLoading.value).toBe(false)
  })
})

describe('I-15 · 页缓存重建入口防重（useReaderPageCache）', () => {
  it('busy 期间重复调用不重复提交任务', async () => {
    vi.stubGlobal('document', { addEventListener: vi.fn(), removeEventListener: vi.fn() })
    vi.stubGlobal('window', {
      setInterval: vi.fn(() => 1),
      clearInterval: vi.fn(),
      getSelection: () => null,
    })
    const cache = useReaderPageCache({
      bookId: ref(1),
      book: ref({ format: 'pdf' } as never),
      pageIndex: ref(1),
    })
    await cache.rebuildPageCache()
    expect(mocks.rebuildPageText).toHaveBeenCalledTimes(1)
    expect(cache.pageCacheBusy.value).toBe(true)

    await cache.rebuildPageCache() // busy 期间再次调用 → 早退
    expect(mocks.rebuildPageText).toHaveBeenCalledTimes(1)

    cache.dispose()
    expect(cache.pageCacheBusy.value).toBe(false)
  })
})

describe('I-10 · 划词菜单右侧出屏钳制（useReaderSelection）', () => {
  it('菜单实宽 520 时 left 被钳制到视口内', async () => {
    const menuEl = { offsetWidth: 520 }
    const anchorNode = {}
    vi.stubGlobal('window', {
      innerWidth: 1920,
      getSelection: () => ({
        toString: () => '选中文本',
        rangeCount: 1,
        anchorNode,
        getRangeAt: () => ({ getBoundingClientRect: () => ({ bottom: 100, left: 1500 }) }),
      }),
    })
    vi.stubGlobal('document', { querySelector: () => menuEl })
    vi.stubGlobal('requestAnimationFrame', (cb: () => void) => {
      cb() // 同步执行，模拟下一帧
      return 1
    })

    const container = ref({
      contains: (node: unknown) => node === anchorNode,
    } as unknown as HTMLElement)
    // 四轮 m3：菜单经模板 ref 注入（不再 document.querySelector）
    const menuRef = ref(menuEl as unknown as HTMLElement)
    const sel = useReaderSelection(container, menuRef)
    sel.onMouseUp({} as MouseEvent)

    expect(sel.selMenu.value.visible).toBe(true)
    expect(sel.selMenu.value.left).toBeLessThanOrEqual(1920 - 520 - 8)
    expect(sel.selMenu.value.left + 520).toBeLessThanOrEqual(1920)
  })
})

describe('I-13b · SSE 静默时轮询补增量触发渲染（复审 Critical 修复）', () => {
  it('flush 链静默后轮询发现新内容 → scheduleFlush 在下一拍渲染，无需新 SSE 事件', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] })
    vi.stubGlobal('crypto', { randomUUID: () => 'key-2' })

    const stream = controllableStream()
    mocks.streamGlobalChat.mockImplementation((_params: unknown, onEvent: (ev: Record<string, unknown>) => void) => {
      stream.setHandler(onEvent)
      return stream
    })
    // 调用#1 = 创建时 loadHistory（空）；调用#2 = t=2000 轮询（DB 已落库 SSE 未送达的 'b'）
    mocks.listGlobalChatMessages
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([
        { id: 1, role: 'assistant', stream_key: 'key-2', content: 'ab', book_id: null, chapter_id: null, ref_para_pos: null, created_at: null },
      ])

    const ai = useGlobalAi()
    ai.input.value = 'hi'
    const sendPromise = ai.send()
    stream.emit({ type: 'delta', text: 'a' })
    await vi.advanceTimersByTimeAsync(80) // t=80 flush 'a' → content='a'，flush 链静默
    const assistant = ai.messages.value.find((m) => m.role === 'assistant')!
    await vi.advanceTimersByTimeAsync(1920) // t=2000 轮询：pendingText='b' + scheduleFlush

    await vi.advanceTimersByTimeAsync(200) // t=2200：flush 触发 → 轮询增量已渲染
    expect(assistant.content).toBe('ab') // 修复前：无新 SSE 事件则永远停在 'a'

    stream.emit({ type: 'end', text: 'ab', citations: [], cached: false })
    stream.resolve()
    await sendPromise
  })
})

describe('I-9 · 视口段落定位坐标系（viewportTopPara 纯函数）', () => {
  it('.reader 内偏移的段落换算 el.offsetTop 后才判定视口顶部', () => {
    const el = { offsetTop: 100, scrollTop: 50 } as HTMLElement
    const paras = [
      { offsetTop: 130, offsetHeight: 20, dataset: { para: '1' } },
      { offsetTop: 170, offsetHeight: 20, dataset: { para: '2' } },
    ] as unknown as HTMLElement[]
    // 段1 换算后 bottom=50 ≤ 74（已滚过视口顶）；段2 bottom=90 > 74 → 当前段=2。
    // 修复前（漏减 el.offsetTop）：150 > 74 → 误判当前段=1（书签偏早 1 段）。
    expect(viewportTopPara(paras, el)).toBe(2)
  })

  it('全部段落在视口上方时返回 null', () => {
    const el = { offsetTop: 100, scrollTop: 1000 } as HTMLElement
    const paras = [{ offsetTop: 130, offsetHeight: 20, dataset: { para: '1' } }] as unknown as HTMLElement[]
    expect(viewportTopPara(paras, el)).toBeNull()
  })
})


describe('I-13c · 阅读页 SSE 静默轮询补增量（useReaderAi）', () => {
  it('SSE 静默后轮询发现落库增量 → 下一拍渲染，flush 后无重复', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] })
    vi.stubGlobal('crypto', { randomUUID: () => 'rk-1' })
    const stream = controllableStream()
    mocks.streamChat.mockImplementation((_bookId: number, _params: unknown, onEvent: (ev: Record<string, unknown>) => void) => {
      stream.setHandler(onEvent)
      return stream
    })
    // useReaderAi 创建时不拉历史；t=2000 的轮询即 listChatMessages 第一次调用
    //（DB 已落库 SSE 未送达的 'b'）
    mocks.listChatMessages.mockResolvedValueOnce([
      { id: 1, role: 'assistant', stream_key: 'rk-1', content: 'ab', book_id: 1, chapter_id: 10, ref_para_pos: null, created_at: null },
    ])
    const ai = useReaderAi({
      bookId: ref(1),
      currentChapterId: ref(10),
      currentChapter: computed(() => ({ id: 10, index: 1, title: '第一章', content_text: '' }) as never),
      scrollEl: ref(null),
      takeSelection: () => '',
      openMindmap: vi.fn(),
      scrollChat: vi.fn(),
    })
    ai.aiInput.value = '解读'
    const sendPromise = ai.sendChat()
    stream.emit({ type: 'delta', text: 'a' })
    await vi.advanceTimersByTimeAsync(80) // t=80 flush 'a' → content='a'，flush 链静默
    const assistant = ai.chatMessages.value.find((m) => m.role === 'assistant')!
    await vi.advanceTimersByTimeAsync(1920) // t=2000 轮询：pendingText='b' + scheduleFlush
    await vi.advanceTimersByTimeAsync(200) // t=2200：flush 触发 → 轮询增量已渲染
    expect(assistant.content).toBe('ab') // 修复前：无新 SSE 事件则永远停在 'a'
    stream.emit({ type: 'end', text: 'ab', citations: [], cached: false })
    stream.resolve()
    await sendPromise
  })
})

describe('I-13d · 流代际守卫：abort 后在途轮询不污染新流（useReaderAi）', () => {
  it('旧流轮询迟到响应被丢弃，新流内容完整', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'Date'] })
    let keySeq = 0
    vi.stubGlobal('crypto', { randomUUID: () => `k-${++keySeq}` })
    let resolveOldPoll!: (v: unknown) => void
    const oldPollPromise = new Promise((resolve) => {
      resolveOldPoll = resolve
    })
    // 流1的轮询即 listChatMessages 第一次调用（fetch 挂起）
    mocks.listChatMessages.mockImplementationOnce(() => oldPollPromise)

    // 流1：abort 时以 AbortError 拒绝（模拟用户点「停止」）
    let reject1!: (err: unknown) => void
    const p1 = new Promise<void>((_resolve, reject) => {
      reject1 = reject
    })
    const stream1 = {
      promise: p1,
      abort: vi.fn(() => reject1(new DOMException('The user aborted a request.', 'AbortError'))),
      setHandler: vi.fn(),
    }
    // 流2：正常收发
    let onEvent2: ((ev: Record<string, unknown>) => void) | null = null
    let resolve2!: () => void
    const p2 = new Promise<void>((resolve) => {
      resolve2 = resolve
    })
    const stream2 = {
      promise: p2,
      abort: vi.fn(),
      setHandler: (fn: (ev: Record<string, unknown>) => void) => {
        onEvent2 = fn
      },
    }
    mocks.streamChat
      .mockImplementationOnce((_b: number, _p: unknown, onEvent: (ev: Record<string, unknown>) => void) => {
        stream1.setHandler(onEvent)
        return stream1
      })
      .mockImplementationOnce((_b: number, _p: unknown, onEvent: (ev: Record<string, unknown>) => void) => {
        stream2.setHandler(onEvent)
        return stream2
      })

    const ai = useReaderAi({
      bookId: ref(1),
      currentChapterId: ref(10),
      currentChapter: computed(() => ({ id: 10, index: 1, title: '第一章', content_text: '' }) as never),
      scrollEl: ref(null),
      takeSelection: () => '',
      openMindmap: vi.fn(),
      scrollChat: vi.fn(),
    })
    ai.aiInput.value = 'q1'
    const sp1 = ai.sendChat()
    await vi.advanceTimersByTimeAsync(2000) // 流1轮询触发（挂起）
    ai.abortChat()
    await sp1

    ai.aiInput.value = 'q2'
    const sp2 = ai.sendChat()
    onEvent2?.({ type: 'delta', text: 'new' })
    await vi.advanceTimersByTimeAsync(80) // flush 'new'
    // 旧流轮询迟到返回（含旧内容）——守卫失效时会写进共享 pendingText 污染新流
    resolveOldPoll([
      { id: 1, role: 'assistant', stream_key: 'k-1', content: 'oldtail', book_id: 1, chapter_id: 10, ref_para_pos: null, created_at: null },
    ])
    await Promise.resolve()
    await vi.advanceTimersByTimeAsync(0)
    const assistants = ai.chatMessages.value.filter((m) => m.role === 'assistant')
    expect(assistants.length).toBe(1)
    expect(assistants[0].content).toBe('new')
    onEvent2?.({ type: 'end', text: 'new', citations: [], cached: false })
    resolve2()
    await sp2
  })
})

describe('I-15b · 重建轮询终态按任务快照书刷新（useReaderPageCache）', () => {
  it('任务进行中切书 → 终态不覆盖新书状态；未切书 → 按快照刷新', async () => {
    let intervalFn: (() => void) | null = null
    vi.stubGlobal('document', { addEventListener: vi.fn(), removeEventListener: vi.fn() })
    vi.stubGlobal('window', {
      setInterval: vi.fn((fn: () => void) => {
        intervalFn = fn
        return 1
      }),
      clearInterval: vi.fn(),
      getSelection: () => null,
    })
    const bookIdRef = ref(1)
    const cache = useReaderPageCache({
      bookId: bookIdRef,
      book: ref({ format: 'pdf' } as never),
      pageIndex: ref(1),
    })
    mocks.getPageTextTask
      .mockResolvedValueOnce({ status: 'running' })
      .mockResolvedValueOnce({ status: 'success' })
    await cache.rebuildPageCache()
    await intervalFn!() // poll#1: running
    await Promise.resolve()
    bookIdRef.value = 2 // 任务进行中切书
    await intervalFn!() // poll#2: success → 当前书≠快照书，不得刷新新书状态
    await Promise.resolve()
    expect(mocks.getPageTextStatus).not.toHaveBeenCalledWith(2)
    expect(cache.pageCacheBusy.value).toBe(false)

    // 未切书场景：重建成功后按快照书刷新状态
    mocks.getPageTextTask.mockResolvedValueOnce({ status: 'success' })
    bookIdRef.value = 1
    await cache.rebuildPageCache()
    await intervalFn!()
    await Promise.resolve()
    expect(mocks.getPageTextStatus).toHaveBeenCalledWith(1)
    cache.dispose()
  })
})
