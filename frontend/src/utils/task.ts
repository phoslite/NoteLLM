import { getTask } from '@/api/tasks'
import type { TaskItem } from '@/types'

/** 全局任务中心轮询触发事件名。 */
export const TASK_SUBMITTED_EVENT = 'app:task-submitted'

/** 通知全局任务中心有新任务提交，立即开始轮询展示进度。 */
export function notifyTaskSubmitted() {
  window.dispatchEvent(new CustomEvent(TASK_SUBMITTED_EVENT))
}

/** 轮询后台任务直至完成（success/failed）；超时抛错。 */
export async function waitForTask(
  taskId: string,
  opts: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<TaskItem> {
  const { intervalMs = 1000, timeoutMs = 10 * 60 * 1000 } = opts
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const t = await getTask(taskId)
    if (t.status === 'success' || t.status === 'failed') return t
    if (Date.now() > deadline) throw new Error(`任务等待超时（>${Math.round(timeoutMs / 1000)}s）`)
    await new Promise((r) => setTimeout(r, intervalMs))
  }
}
