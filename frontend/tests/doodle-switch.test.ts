import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick, ref } from 'vue'
import { useReaderDoodle } from '../src/composables/useReaderDoodle'
import type { AnnotationElement } from '../src/types'

/**
 * 终审 §6.9 + 三审 Minor-3 回归测试（docs/审查报告-20260810-终审.md §6.9）：
 * - C1：切书重挂载时 dispose 不得把旧书涂鸦写入新书（bookId 已指向新书）；
 * - I4：切书后迟到的加载响应不得覆盖/写入新书；
 * - I5：防抖保存定时器在切书窗口内不得写错书；
 * - Minor-3：只读访问（加载后无改动）不得产生写请求；有改动才落盘。
 */
const mocks = vi.hoisted(() => ({
  getPageAnnotations: vi.fn(async () => [] as AnnotationElement[]),
  savePageAnnotations: vi.fn(async () => null),
}))

vi.mock('@/api/annotations', () => ({
  getPageAnnotations: mocks.getPageAnnotations,
  savePageAnnotations: mocks.savePageAnnotations,
}))

describe('useReaderDoodle 跨书守卫（终审 §6.9）+ 脏标记（三审 Minor-3）', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    mocks.getPageAnnotations.mockReset()
    mocks.savePageAnnotations.mockReset()
    mocks.getPageAnnotations.mockResolvedValue([])
    mocks.savePageAnnotations.mockResolvedValue(null)
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  function makeDoodle(bookId: ReturnType<typeof ref<number>>, pageIndex: ReturnType<typeof ref<number | null>>) {
    return useReaderDoodle({ bookId, pageIndex, onAskCrop: vi.fn() })
  }

  it('C1：dispose 时已切书 → 旧书涂鸦不写入新书', async () => {
    const bookId = ref(1)
    const pageIndex = ref<number | null>(1)
    const doodle = makeDoodle(bookId, pageIndex)
    await doodle.loadDoodle(1)
    // 模拟 App.vue 按 fullPath 重挂载：bookId 已指向新书后旧组件 dispose
    bookId.value = 2
    doodle.dispose()
    expect(mocks.savePageAnnotations).not.toHaveBeenCalled()
  })

  it('Minor-3：只读访问（loadDoodle 后无改动）dispose 不产生写请求', async () => {
    const bookId = ref(1)
    const pageIndex = ref<number | null>(1)
    const doodle = makeDoodle(bookId, pageIndex)
    await doodle.loadDoodle(1)
    await nextTick()
    doodle.dispose()
    expect(mocks.savePageAnnotations).not.toHaveBeenCalled()
  })

  it('同书 dispose 有改动时仍正常 flush（防回归：≤800ms 涂鸦不丢）', async () => {
    const bookId = ref(1)
    const pageIndex = ref<number | null>(1)
    const doodle = makeDoodle(bookId, pageIndex)
    await doodle.loadDoodle(1)
    await nextTick()
    doodle.doodleElements.value = [{ kind: 'pen', points: [0, 0, 5, 5], color: '#000', width: 2 } as AnnotationElement]
    await nextTick() // 让 deep-watch 回调执行（dirty=true + schedule）
    doodle.dispose()
    expect(mocks.savePageAnnotations).toHaveBeenCalledTimes(1)
    expect(mocks.savePageAnnotations).toHaveBeenCalledWith(1, 1, expect.any(Array))
  })

  it('I4：切书后迟到的加载响应不写入新书状态', async () => {
    const bookId = ref(1)
    const pageIndex = ref<number | null>(1)
    const doodle = makeDoodle(bookId, pageIndex)
    let resolveFetch: (v: AnnotationElement[]) => void = () => {}
    mocks.getPageAnnotations.mockReturnValueOnce(new Promise<AnnotationElement[]>((r) => { resolveFetch = r }))
    const loading = doodle.loadDoodle(1)
    bookId.value = 2 // 加载在途切书
    resolveFetch([{ kind: 'pen', points: [0, 0, 10, 10], color: '#000', width: 2 } as AnnotationElement])
    await loading
    expect(doodle.doodleElements.value).toEqual([]) // 旧书数据未写入
  })

  it('I5：防抖保存定时器在切书窗口内不写错书', async () => {
    const bookId = ref(1)
    const pageIndex = ref<number | null>(1)
    const doodle = makeDoodle(bookId, pageIndex)
    await doodle.loadDoodle(1)
    doodle.doodleElements.value = [{ kind: 'pen', points: [0, 0, 5, 5], color: '#000', width: 2 } as AnnotationElement]
    await nextTick() // 让 watch 触发 scheduleDoodleSave
    bookId.value = 2 // 定时器窗口内切书
    vi.advanceTimersByTime(900)
    expect(mocks.savePageAnnotations).not.toHaveBeenCalled()
    // 同书场景仍正常保存（防回归）
    bookId.value = 1
    doodle.doodleElements.value = [...doodle.doodleElements.value]
    await nextTick()
    vi.advanceTimersByTime(900)
    expect(mocks.savePageAnnotations).toHaveBeenCalledTimes(1)
    expect(mocks.savePageAnnotations).toHaveBeenCalledWith(1, 1, expect.any(Array))
  })
})