import { get, post } from './client'

/** PDF 页缓存状态：已缓存页数 / 总页数。 */
export interface PageCacheStatus {
  total: number
  cached: number
}

/** 读取指定页缓存文本（未缓存时 text 为 null）。 */
export function getPageText(bookId: number, pageIndex: number) {
  return get<{ page_index: number; cached: boolean; text: string | null }>(
    `/books/${bookId}/page-text/${pageIndex}`,
  )
}

/** 查看本书页缓存覆盖情况。 */
export function getPageTextStatus(bookId: number) {
  return get<PageCacheStatus>(`/books/${bookId}/page-text/status`)
}

/** 重新提取本页（强制覆盖缓存）。 */
export function reextractPage(bookId: number, pageIndex: number) {
  return post<{ page_index: number; cached: boolean; text: string }>(
    `/books/${bookId}/page-text/${pageIndex}`,
    {},
  )
}

/** 重建本书页缓存（后台任务）；force=true 全部重提取，false 仅补缺失页。 */
export function rebuildPageText(bookId: number, force = false) {
  return post<{ task_id: string }>(`/books/${bookId}/page-text/rebuild`, { force })
}

/** 查询页缓存重建任务状态。 */
export function getPageTextTask(bookId: number, taskId: string) {
  return get<{ status: string; result?: unknown; error?: string | null }>(
    `/books/${bookId}/page-text/tasks/${taskId}`,
  )
}
