import type { BookAssetView, TaskStatus } from '@/types'
import { get, post } from './client'

/** 触发书籍总结为 RAG/Skill（后台任务），返回 task_id。 */
export function summarizeBook(bookId: number) {
  return post<{ task_id: string }>(`/books/${bookId}/summarize`)
}

/** 读完归档：PDF 先视觉通读全书并缓存 → 文本模型总结 RAG/Skill → 标记读完（M9）。 */
export function archiveBook(bookId: number) {
  return post<{ task_id: string }>(`/books/${bookId}/archive`)
}

/** 轮询任务状态：{status, result, error}。 */
export function getTask(taskId: string) {
  return get<TaskStatus>(`/tasks/${taskId}`)
}

/** 读取书籍的 RAG/Skill 资产。 */
export function getBookAsset(bookId: number) {
  return get<BookAssetView>(`/books/${bookId}/asset`)
}