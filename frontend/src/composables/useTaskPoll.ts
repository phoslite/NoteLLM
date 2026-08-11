import { onBeforeUnmount } from 'vue'
import { waitForTask } from '@/utils/task'
import type { TaskItem } from '@/types'

/**
 * 任务轮询组合式函数（三审 Major-1：卸载时中止轮询，避免组件销毁后继续请求）。
 *
 * - run(taskId, opts) 包装 waitForTask，内部注册顶层 onBeforeUnmount，
 *   组件卸载时自动 abort，waitForTask 收到 AbortError 后停止轮询。
 * - 调用方传入的 signal 与组件卸载信号合并（AbortSignal.any 优先；
 *   旧内核降级为双向桥接），任一触发均中止轮询（四轮 m2：不再静默覆盖调用方 signal）。
 */
export function useTaskPoll() {
  const controller = new AbortController()
  onBeforeUnmount(() => controller.abort())

  async function run(taskId: string, opts: { intervalMs?: number; timeoutMs?: number; signal?: AbortSignal } = {}): Promise<TaskItem> {
    const { signal: callerSignal, ...rest } = opts
    if (!callerSignal) return waitForTask(taskId, { ...rest, signal: controller.signal })
    if (typeof AbortSignal.any === 'function') {
      return waitForTask(taskId, { ...rest, signal: AbortSignal.any([controller.signal, callerSignal]) })
    }
    // 旧内核（无 AbortSignal.any）降级：双向桥接两个信号
    const bridge = new AbortController()
    const onUnmount = () => bridge.abort()
    const onCaller = () => bridge.abort()
    controller.signal.addEventListener('abort', onUnmount, { once: true })
    callerSignal.addEventListener('abort', onCaller, { once: true })
    try {
      return await waitForTask(taskId, { ...rest, signal: bridge.signal })
    } finally {
      controller.signal.removeEventListener('abort', onUnmount)
      callerSignal.removeEventListener('abort', onCaller)
    }
  }

  return { run, signal: controller.signal }
}