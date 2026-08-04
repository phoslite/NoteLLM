import type { BookDetail, BookItem } from '@/types'
import { del, get, patch, post } from './client'

export function listBooks(params?: { folder_id?: number; q?: string }) {
  return get<BookItem[]>('/books', params)
}

export function reorderBooks(orderedIds: number[]) {
  return post<{ reordered: number }>('/books/reorder', { ordered_ids: orderedIds })
}

export function getBook(bookId: number) {
  return get<BookDetail>(`/books/${bookId}`)
}

/** 上传结果（决策 35 两段式）：书籍字段平铺返回（已入架），task_id 为后台处理任务（任务中心展示）。 */
export type UploadResult = BookItem & { task_id: string }

export function uploadBook(file: File, title?: string, author?: string) {
  const form = new FormData()
  form.append('file', file)
  if (title) form.append('title', title)
  if (author) form.append('author', author)
  return post<UploadResult>('/books', form)
}

export function updateBook(bookId: number, body: Partial<Pick<BookItem, 'title' | 'status' | 'progress' | 'folder_id'> & { tags: string[] }>) {
  return patch<BookItem>(`/books/${bookId}`, body)
}

export function deleteBook(bookId: number) {
  return del<null>(`/books/${bookId}`)
}