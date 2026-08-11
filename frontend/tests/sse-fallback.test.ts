import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { streamChat } from '../src/api/chat'

/**
 * M1 回归测试（四轮审查 Major-1）：
 * 无 AbortSignal.any 的旧内核（Chrome<116 / Safari<17）下，SSE 空闲超时必须仍能中断 fetch——
 * idle 定时器触发时经反向桥接 abort 外层 controller，否则 reader.read() 永久 pending，
 * 循环内 fired 检查不可达，120s 空闲超时形同虚设。
 */
describe('M1 · SSE 空闲超时降级路径（无 AbortSignal.any）', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    // 模拟旧内核：AbortSignal.any 不存在
    vi.stubGlobal('AbortSignal', { ...globalThis.AbortSignal, any: undefined })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.useRealTimers()
  })

  it('idle 超时触发后 promise 以「空闲超时」拒绝（fetch 被中断）', async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
      const signal = init?.signal as AbortSignal
      // 模拟「服务器完全静默」：read() 永久 pending，直到 signal 中止才报错
      const stream = new ReadableStream<Uint8Array>({
        pull(controller) {
          return new Promise<void>((resolve) => {
            if (signal.aborted) {
              controller.error(signal.reason ?? new DOMException('aborted', 'AbortError'))
              resolve()
              return
            }
            signal.addEventListener(
              'abort',
              () => {
                controller.error(signal.reason ?? new DOMException('aborted', 'AbortError'))
                resolve()
              },
              { once: true },
            )
          })
        },
      })
      return new Response(stream, { status: 200 })
    })
    vi.stubGlobal('fetch', fetchMock)

    const onEvent = vi.fn()
    const { promise } = streamChat(1, { question: '挂起问题' }, onEvent)

    // 先挂断言再推进计时：避免 timer 触发瞬间的 rejection 被记为 unhandled
    const rejection = expect(promise).rejects.toThrow(/空闲超时/)
    // 推进超过 120s 空闲阈值
    await vi.advanceTimersByTimeAsync(120001)

    await rejection
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(onEvent).not.toHaveBeenCalled()
  })

  it('主链路（有 AbortSignal.any）仍可用：收到数据后 idle 计时重置、事件正常回调', async () => {
    vi.unstubAllGlobals() // 恢复真实 AbortSignal.any
    const encoder = new TextEncoder()
    const fetchMock = vi.fn(async () => {
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(encoder.encode('data: {"type":"delta","text":"你好"}\n\n'))
          controller.close()
        },
      })
      return new Response(stream, { status: 200 })
    })
    vi.stubGlobal('fetch', fetchMock)

    const onEvent = vi.fn()
    const { promise } = streamChat(1, { question: 'hi' }, onEvent)
    await vi.advanceTimersByTimeAsync(100)
    await promise

    expect(onEvent).toHaveBeenCalledTimes(1)
    expect(onEvent.mock.calls[0][0]).toMatchObject({ type: 'delta', text: '你好' })
  })
})