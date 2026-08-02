import type { BookItem, ChapterContent, ChapterItem, NoteItem, NoteType, ReadingProgress } from '@/types'
import { del, get, patch, post } from './client'

export function getChapterContent(bookId: number, chapterId: number) {
  return get<ChapterContent>(`/books/${bookId}/chapters/${chapterId}`)
}

export function setChapterRead(bookId: number, chapterId: number, read: boolean) {
  return patch<ChapterItem>(`/books/${bookId}/chapters/${chapterId}/read`, { read })
}

export function setAllChaptersRead(bookId: number, read: boolean) {
  return patch<BookItem>(`/books/${bookId}/read-all`, { read })
}

export function getProgress(bookId: number) {
  return get<ReadingProgress>(`/books/${bookId}/progress`)
}

export function saveProgress(
  bookId: number,
  body: { chapter_id: number; position: number; mark_read?: boolean },
) {
  return post<ReadingProgress>(`/books/${bookId}/progress`, body)
}

export function listNotes(bookId: number) {
  return get<NoteItem[]>(`/books/${bookId}/notes`)
}

export function createNote(
  bookId: number,
  body: { chapter_id: number | null; quote_text?: string; note_text?: string; note_type: NoteType },
) {
  return post<NoteItem>(`/books/${bookId}/notes`, body)
}

export function updateNote(noteId: number, body: { note_text?: string; note_type?: NoteType }) {
  return patch<NoteItem>(`/notes/${noteId}`, body)
}

export function deleteNote(noteId: number) {
  return del<null>(`/notes/${noteId}`)
}

/** 笔记导出下载地址（Markdown / PDF，M10）。 */
export const exportNotesUrl = (bookId: number) => `/api/books/${bookId}/notes/export`
export const exportNotesPdfUrl = (bookId: number) => `/api/books/${bookId}/notes/export?fmt=pdf`