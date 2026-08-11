import { getTask } from '@/api/tasks'
import type { TaskItem } from '@/types'

/** 全局任务中心轮询触发事件名。 */
export const TASK_SUBMITTED_EVENT = 'app:task-submitted'

/** 通知全局任务中心有新任务提交，立即开始轮询展示进度。 */
export function notifyTaskSubmitted() {
  window.dispatchEvent(new CustomEvent(TASK_SUBMITTED_EVENT))
}

/** 取「最近 n 条已终态任务」（C-I4 修复）：显式按 created_at 降序取最新，顺序最新在前。 */
export function latestFinishedTasks(all: TaskItem[], n = 3): TaskItem[] {
  return all
    .filter((t) => t.status === 'success' || t.status === 'failed')
    .sort((x, y) => String(y.created_at ?? '').localeCompare(String(x.created_at ?? '')))
    .slice(0, n)
}

/** 构造 AbortError：调用方按 err.name === 'AbortError' 静默忽略（组件卸载取消）。 */
function abortError(): Error {
  const e = new Error('任务等待已取消')
  e.name = 'AbortError'
  return e
}

/** 轮询后台任务直至完成（success/failed）；not_found 视为终态抛错；超时抛错；signal 中止时抛 AbortError。 */
export async function waitForTask(
  taskId: string,
  opts: { intervalMs?: number; timeoutMs?: number; signal?: AbortSignal } = {},
): Promise<TaskItem> {
  const { intervalMs = 1000, timeoutMs = 10 * 60 * 1000, signal } = opts
  const deadline = Date.now() + timeoutMs
  let aborted = false
  let wake: (() => void) | null = null
  let sleepTimer: ReturnType<typeof setTimeout> | null = null
  // 终审 §6.9：单一 abort 监听（原实现每轮循环挂 once 监听，180s 轮询累积约 120 个）
  const onAbort = () => { aborted = true; wake?.() }
  signal?.addEventListener('abort', onAbort, { once: true })
  try {
    for (;;) {
      if (aborted || signal?.aborted) throw abortError()
      const t = await getTask(taskId)
      if (t.status === 'success' || t.status === 'failed') return t
      // 终审 §6.9：任务 7 天清理后旧 task_id 轮询不再白等至超时
      if (t.status === 'not_found') throw new Error('任务不存在或已过期清理，请重新提交')
      if (Date.now() > deadline) throw new Error(`任务等待超时（>${Math.round(timeoutMs / 1000)}s）`)
      await new Promise<void>((resolve) => {
        wake = resolve
        sleepTimer = setTimeout(() => { wake = null; resolve() }, intervalMs)
      })
      wake = null
    }
  } finally {
    if (sleepTimer !== null) clearTimeout(sleepTimer)
    signal?.removeEventListener('abort', onAbort)
  }
}
