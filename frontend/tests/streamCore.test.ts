import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  FLUSH_INTERVAL_MS, MATH_MAX_WAIT_MS, POLL_INTERVAL_MS, SSE_ACTIVE_GUARD_MS,
  THINKING_FLUSH_MS, hasUnclosedMath, isAbortError, uuid,
} from '../src/utils/streamCore'

/** MO3 阶段1：流式共享常量与纯函数单测（原两个内核逐字节内联的重复项）。 */

describe('常量组（MO3）', () => {
  it('渲染节流/公式等待/轮询/思考节流/SSE 活跃守卫值与原内核一致', () => {
    expect(FLUSH_INTERVAL_MS).toBe(80)
    expect(MATH_MAX_WAIT_MS).toBe(500)
    expect(POLL_INTERVAL_MS).toBe(2000)
    expect(THINKING_FLUSH_MS).toBe(150)
    expect(SSE_ACTIVE_GUARD_MS).toBe(500)
  })
})

describe('hasUnclosedMath', () => {
  it('成对 $$…$$ 与 $…$ 视为闭合', () => {
    expect(hasUnclosedMath('')).toBe(false)
    expect(hasUnclosedMath('普通文本')).toBe(false)
    expect(hasUnclosedMath('a$b$c')).toBe(false)
    expect(hasUnclosedMath('a$$b$$c')).toBe(false)
    expect(hasUnclosedMath('$a$ 与 $$b$$ 混合')).toBe(false)
  })

  it('奇数个 $$ 或 $ 视为未闭合', () => {
    expect(hasUnclosedMath('$$x')).toBe(true)
    expect(hasUnclosedMath('a$b')).toBe(true)
    expect(hasUnclosedMath('$$a$$ 与 $b')).toBe(true)
    expect(hasUnclosedMath('a$$b$')).toBe(true)
  })
})

describe('isAbortError', () => {
  it('仅 DOMException AbortError 为真', () => {
    expect(isAbortError(new DOMException('aborted', 'AbortError'))).toBe(true)
    expect(isAbortError(new Error('普通错误'))).toBe(false)
    expect(isAbortError('string error')).toBe(false)
    expect(isAbortError(null)).toBe(false)
    expect(isAbortError(new DOMException('x', 'TimeoutError'))).toBe(false)
  })
})

describe('uuid', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('优先使用 crypto.randomUUID', () => {
    vi.stubGlobal('crypto', { randomUUID: () => 'uuid-1' })
    expect(uuid()).toBe('uuid-1')
  })

  it('无 randomUUID 时回退时间戳+随机串兜底', () => {
    vi.stubGlobal('crypto', {})
    const a = uuid()
    const b = uuid()
    expect(a).toMatch(/^\d+-[0-9a-f]+$/)
    expect(a).not.toBe(b)
  })
})