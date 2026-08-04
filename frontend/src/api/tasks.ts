import type { TaskItem } from '@/types'
import { get } from './client'

/** 后台任务列表（创建时间倒序），任务中心轮询用。 */
export function listTasks() {
  return get<TaskItem[]>('/tasks')
}

/** 查询单个后台任务状态：{status, progress, stage, result, error}。 */
export function getTask(taskId: string) {
  return get<TaskItem>(`/tasks/${taskId}`)
}
