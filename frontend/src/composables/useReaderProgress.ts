import { ref, type ComputedRef, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import { saveProgress } from '@/api/reading'
import type { ChapterItem } from '@/types'

export interface ReadingProgressCache {
  chapter_id: number | null
  position: number
}

export interface ReaderProgress {
  progressCache: Ref<ReadingProgressCache | null>
  setCache: (p: ReadingProgressCache | null) => void
  markChapterOpened: () => void
  applyRestore: (chapterId: number, restore: boolean) => void
  onScroll: () => void
  saveNow: () => Promise<void>
  checkAutoRead: () => Promise<void>
  resetForBook: () => void
  dispose: () => void
}

/** 阅读进度：滚动防抖保存、章节位置恢复、自动标记读完（≥10s 且滚动到底）。 */
export function useReaderProgress(opts: {
  bookId: ComputedRef<number>
  scrollEl: Ref<HTMLElement | null>
  currentChapterId: Ref<number | null>
  getCurrentChapter: () => ChapterItem | undefined
  /** 章节自动读完后的回调：刷新书籍详情与书架。 */
  onAutoRead: () => Promise<void>
  /** 进度保存成功后的书架刷新。 */
  refreshShelf: () => void
}): ReaderProgress {
  const { bookId, scrollEl, currentChapterId, getCurrentChapter, onAutoRead, refreshShelf } = opts
  const AUTO_READ_MS = 10_000

  const progressCache = ref<ReadingProgressCache | null>(null)
  let saveTimer: ReturnType<typeof setTimeout> | null = null
  let lastPos = { chapterId: 0, position: 0 }
  let chapterOpenedAt = Date.now()
  let autoMarkedChapter = new Set<number>()

  function markChapterOpened() {
    chapterOpenedAt = Date.now()
  }

  function applyRestore(chapterId: number, restore: boolean) {
    const el = scrollEl.value
    if (!el) return
    if (restore) {
      const saved = progressCache.value
      const pos = saved?.chapter_id === chapterId ? saved.position : 0
      el.scrollTop = pos * (el.scrollHeight - el.clientHeight)
      lastPos = { chapterId, position: pos }
    } else {
      el.scrollTop = 0
      lastPos = { chapterId, position: 0 }
    }
  }

  function onScroll() {
    const el = scrollEl.value
    if (!el || !currentChapterId.value) return
    const max = el.scrollHeight - el.clientHeight
    const position = max > 0 ? Math.min(1, Math.max(0, el.scrollTop / max)) : 0
    lastPos = { chapterId: currentChapterId.value, position }
    if (saveTimer) clearTimeout(saveTimer)
    saveTimer = setTimeout(() => void saveNow(), 600)
    void checkAutoRead()
  }

  async function saveNow() {
    if (!lastPos.chapterId) return
    const { chapterId, position } = lastPos
    try {
      const p = await saveProgress(bookId.value, { chapter_id: chapterId, position })
      progressCache.value = p
      refreshShelf()
    } catch {
      /* 保存失败静默，下次滚动重试 */
    }
  }

  function atScrollBottom(el: HTMLElement) {
    return el.scrollHeight - el.scrollTop - el.clientHeight <= 4
  }

  async function checkAutoRead() {
    const el = scrollEl.value
    const cid = currentChapterId.value
    if (!el || !cid) return
    if (autoMarkedChapter.has(cid)) return
    const chapter = getCurrentChapter()
    if (!chapter || chapter.read_flag) return
    if (Date.now() - chapterOpenedAt < AUTO_READ_MS) return
    if (!atScrollBottom(el)) return
    autoMarkedChapter.add(cid)
    try {
      const p = await saveProgress(bookId.value, { chapter_id: cid, position: 1, mark_read: true })
      progressCache.value = p
      await onAutoRead()
      ElMessage.success(`第${chapter.index}章「${chapter.title}」已读完`)
    } catch {
      autoMarkedChapter.delete(cid)
    }
  }

  function setCache(p: ReadingProgressCache | null) {
    progressCache.value = p
  }

  function resetForBook() {
    if (saveTimer) clearTimeout(saveTimer)
    saveTimer = null
    autoMarkedChapter = new Set()
  }

  function dispose() {
    if (saveTimer) clearTimeout(saveTimer)
    saveTimer = null
    void saveNow()
  }

  return { progressCache, setCache, markChapterOpened, applyRestore, onScroll, saveNow, checkAutoRead, resetForBook, dispose }
}
