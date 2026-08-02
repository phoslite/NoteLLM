import type { AnnotationElement, BookmarkItem } from '@/types'
import { del, get, patch, post, put } from './client'

/* ---------- 书签 ---------- */

export function listBookmarks(bookId: number) {
  return get<BookmarkItem[]>(`/books/${bookId}/bookmarks`)
}

export function createBookmark(
  bookId: number,
  body: {
    chapter_id: number | null
    page_index?: number | null
    para_pos?: string | null
    title: string
    note?: string
    group_name?: string
  },
) {
  return post<BookmarkItem>(`/books/${bookId}/bookmarks`, body)
}

export function updateBookmark(
  bookmarkId: number,
  body: { title?: string; note?: string; group_name?: string },
) {
  return patch<BookmarkItem>(`/bookmarks/${bookmarkId}`, body)
}

export function deleteBookmark(bookmarkId: number) {
  return del<null>(`/bookmarks/${bookmarkId}`)
}

/* ---------- 页图涂鸦 ---------- */

export function getPageAnnotations(bookId: number, pageIndex: number) {
  return get<AnnotationElement[]>(`/books/${bookId}/annotations`, { page_index: pageIndex })
}

export function savePageAnnotations(bookId: number, pageIndex: number, elements: AnnotationElement[]) {
  return put<number>(`/books/${bookId}/annotations`, { page_index: pageIndex, elements })
}
