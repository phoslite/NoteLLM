import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
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

  /** 近期阅读：按 last_opened_at 倒序（后端暂未排序时前端兜底）；P3-4：computed 缓存，避免每次调用重排。 */
  const recentBooks = computed(() =>
    [...books.value].sort((a, b) => String(b.last_opened_at ?? '').localeCompare(String(a.last_opened_at ?? ''))).slice(0, 5))

  return { books, loading, fetchBooks, recentBooks }
})