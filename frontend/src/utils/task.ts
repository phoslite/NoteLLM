import { getTask } from '@/api/tasks'
import type { TaskItem } from '@/types'

/** 全局任务中心轮询触发事件名。 */
export const TASK_SUBMITTED_EVENT = 'app:task-submitted'

/** 通知全局任务中心有新任务提交，立即开始轮询展示进度。 */
export function notifyTaskSubmitted() {
  window.dispatchEvent(new CustomEvent(TASK_SUBMITTED_EVENT))
}

/** 构造 AbortError：调用方按 err.name === 'AbortError' 静默忽略（组件卸载取消）。 */
function abortError(): Error {
  const e = new Error('任务等待已取消')
  e.name = 'AbortError'
  return e
}

/** 轮询后台任务直至完成（success/failed）；超时抛错；signal 中止时抛 AbortError。 */
export async function waitForTask(
  taskId: string,
  opts: { intervalMs?: number; timeoutMs?: number; signal?: AbortSignal } = {},
): Promise<TaskItem> {
  const { intervalMs = 1000, timeoutMs = 10 * 60 * 1000, signal } = opts
  const deadline = Date.now() + timeoutMs
  for (;;) {
    if (signal?.aborted) throw abortError()
    const t = await getTask(taskId)
    if (t.status === 'success' || t.status === 'failed') return t
    if (Date.now() > deadline) throw new Error(`任务等待超时（>${Math.round(timeoutMs / 1000)}s）`)
    await new Promise<void>((resolve) => {
      const timer = setTimeout(resolve, intervalMs)
      signal?.addEventListener('abort', () => { clearTimeout(timer); resolve() }, { once: true })
    })
  }
}
