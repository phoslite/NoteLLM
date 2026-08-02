import { defineStore } from 'pinia'
import { ref } from 'vue'
import { listBooks } from '@/api/books'
import type { BookItem } from '@/types'

export const useBookStore = defineStore('book', () => {
  const books = ref<BookItem[]>([])
  const loading = ref(false)

  async function fetchBooks() {
    loading.value = true
    try {
      books.value = await listBooks()
    } finally {
      loading.value = false
    }
  }

  /** 近期阅读：按 last_opened_at 倒序（后端暂未排序时前端兜底） */
  const recentBooks = () =>
    [...books.value].sort((a, b) => String(b.last_opened_at ?? '').localeCompare(String(a.last_opened_at ?? ''))).slice(0, 5)

  return { books, loading, fetchBooks, recentBooks }
})