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

/** 阅读进度：滚动防抖保存、章节位置恢复、自动标记读完（可见时长≥10s 且滚动到底）。
 *  阅读时长做页面可见性感知：切换标签页/最小化期间不计入，恢复可见后继续累计。 */
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
  let lastPos = { bookId: 0, chapterId: 0, position: 0 }  // F14：绑定书 id，防切书窗口期旧进度写入新书
  let visibleAccumMs = 0
  /** 本章已累计的「页面可见」阅读时长（ms），隐藏/最小化期间不增长。 */
  let visibleSinceAt: number | null = null
  let autoMarkedChapter = new Set<number>()

  /** 可见性切换：隐藏时结算当前可见段，恢复可见时重新起算。 */
  function onVisibilityChange() {
    if (document.visibilityState === 'visible') {
      visibleSinceAt = Date.now()
      return
    }
    if (visibleSinceAt != null) {
      visibleAccumMs += Date.now() - visibleSinceAt
      visibleSinceAt = null
    }
  }

  /** 本章累计的可见阅读时长（ms）。 */
  function visibleElapsedMs(): number {
    const now = Date.now()
    return visibleAccumMs + (visibleSinceAt != null ? now - visibleSinceAt : 0)
  }

  function markChapterOpened() {
    visibleAccumMs = 0
    visibleSinceAt = document.visibilityState === 'visible' ? Date.now() : null
  }

  function applyRestore(chapterId: number, restore: boolean) {
    const el = scrollEl.value
    if (!el) return
    if (restore) {
      const saved = progressCache.value
      const pos = saved?.chapter_id === chapterId ? saved.position : 0
      el.scrollTop = pos * (el.scrollHeight - el.clientHeight)
      lastPos = { bookId: bookId.value, chapterId, position: pos }
    } else {
      el.scrollTop = 0
      lastPos = { bookId: bookId.value, chapterId, position: 0 }
    }
  }

  function onScroll() {
    const el = scrollEl.value
    if (!el || !currentChapterId.value) return
    const max = el.scrollHeight - el.clientHeight
    const position = max > 0 ? Math.min(1, Math.max(0, el.scrollTop / max)) : 0
    lastPos = { bookId: bookId.value, chapterId: currentChapterId.value, position }
    if (saveTimer) clearTimeout(saveTimer)
    saveTimer = setTimeout(() => void saveNow(), 600)
  }

  async function saveNow() {
    if (!lastPos.chapterId) return
    if (lastPos.bookId !== bookId.value) return  // F14：切书窗口期旧书位置不写入新书
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
    if (visibleElapsedMs() < AUTO_READ_MS) return
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
    visibleAccumMs = 0
    visibleSinceAt = null
    lastPos = { bookId: 0, chapterId: 0, position: 0 }  // F14：切书清空旧进度缓存
  }

  function dispose() {
    if (saveTimer) clearTimeout(saveTimer)
    saveTimer = null
    document.removeEventListener('visibilitychange', onVisibilityChange)
    void saveNow()
  }

  document.addEventListener('visibilitychange', onVisibilityChange)

  return { progressCache, setCache, markChapterOpened, applyRestore, onScroll, saveNow, checkAutoRead, resetForBook, dispose }
}
