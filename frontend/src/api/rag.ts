import type { BookAssetBrief, BookAssetView } from '@/types'
import { del, get, post } from './client'

/** 触发书籍总结为 RAG/Skill（后台任务），返回 task_id。 */
export function summarizeBook(bookId: number) {
  return post<{ task_id: string }>(`/books/${bookId}/summarize`)
}

/** 读完归档：PDF 先视觉通读全书并缓存 → 文本模型总结 RAG/Skill → 标记读完（M9）。 */
export function archiveBook(bookId: number) {
  return post<{ task_id: string }>(`/books/${bookId}/archive`)
}

/** 轮询任务状态（统一走 /api/tasks/{id}，TaskItem 含 progress/stage）。 */
export { getTask } from './tasks'

/** 删除资产内第 index 项（0 基）：rag.key_points / rag.chunks / skill.skills。 */
export function deleteAssetItem(
  bookId: number,
  kind: 'rag' | 'skill',
  section: 'key_points' | 'chunks' | 'skills',
  index: number,
) {
  return del<{ content: unknown }>(`/books/${bookId}/asset/${kind}/${section}/${index}`)
}

/** 跨书资产去重合并：按书籍内容 hash（原文件 sha256）合并相同资产的书籍（返回 {rag, skill} 合并数）。 */
export function dedupeAssets() {
  return post<{ rag: number; skill: number }>(`/assets/dedupe`)
}

/** 读取书籍的 RAG/Skill 资产。 */
export function getBookAsset(bookId: number) {
  return get<BookAssetView>(`/books/${bookId}/asset`)
}

/** 批量资产摘要（审查 A-6）：全部书籍的资产状态一次返回，资产页列表不再逐书请求。 */
export function listAssetBriefs() {
  return get<Record<number, BookAssetBrief>>('/books/assets')
}