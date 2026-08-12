import { describe, expect, it, vi } from 'vitest'
import { createPollLoop } from '../src/utils/taskCenter'

/** P2-1 回归：关闭竞态——stop() 后在途 poll 结果必须被丢弃，循环退出；重新 start 可恢复。 */
describe('createPollLoop（P2-1 关闭竞态）', () => {
  it('stop 后在途 poll 的结果被丢弃，且不再继续轮询', async () => {
    const onData = vi.fn()
    const onIdle = vi.fn()
    let pollCount = 0
    let release!: () => void
    const gate = new Promise<void>((r) => { release = r })
    const loop = createPollLoop<number>({
      poll: async () => {
        pollCount += 1
        await gate // 在途 poll 挂起，模拟 closePanel 瞬间的未返回请求
        return { more: true, data: pollCount }
      },
      onData,
      sleep: vi.fn(async () => {}),
    })
    loop.start()
    await new Promise((r) => setTimeout(r, 0)) // 让第一个 poll 进入挂起
    loop.stop() // 用户点击 ✕ 关闭面板
    release()
    await new Promise((r) => setTimeout(r, 20))
    expect(pollCount).toBe(1) // 只发起了这一次
    expect(onData).not.toHaveBeenCalled() // 结果被丢弃，不会重新打开面板
    expect(onIdle).not.toHaveBeenCalled() // 用户 stop 退场不算自然停止
  })

  it('more=false 时轮询自然停止（不再调用 poll，onIdle 触发一次）', async () => {
    const onData = vi.fn()
    const onIdle = vi.fn()
    const poll = vi.fn(async () => ({ more: false, data: 1 }))
    const loop = createPollLoop<number>({ poll, onData, sleep: vi.fn(async () => {}), onIdle })
    loop.start()
    await new Promise((r) => setTimeout(r, 20))
    expect(onData).toHaveBeenCalledTimes(1)
    expect(poll).toHaveBeenCalledTimes(1)
    expect(onIdle).toHaveBeenCalledTimes(1)
  })

  it('单次 poll 抛错时静默退出（与组件 catch→false 语义一致）', async () => {
    const onData = vi.fn()
    const poll = vi.fn(async () => { throw new Error('网络错误') })
    const loop = createPollLoop<number>({ poll, onData, sleep: vi.fn(async () => {}) })
    loop.start()
    await new Promise((r) => setTimeout(r, 20))
    expect(onData).not.toHaveBeenCalled()
  })

  it('stop 后由新事件 start 可恢复轮询（任务提交事件驱动重开）', async () => {
    const onData = vi.fn()
    let polls = 0
    const loop = createPollLoop<number>({
      poll: async () => {
        polls += 1
        return { more: true, data: polls }
      },
      onData,
      sleep: async () => { await new Promise((r) => setTimeout(r, 1)) }, // 真实 tick：纯微任务 sleep 会饿死事件循环
    })
    loop.start()
    await new Promise((r) => setTimeout(r, 0))
    loop.stop()
    loop.start() // 模拟 TASK_SUBMITTED_EVENT 再次触发
    await new Promise((r) => setTimeout(r, 30))
    loop.stop() // 收尾：避免轮询循环拖住测试进程
    expect(polls).toBeGreaterThanOrEqual(2)
    expect(onData.mock.calls.length).toBeGreaterThanOrEqual(2)
  })
})