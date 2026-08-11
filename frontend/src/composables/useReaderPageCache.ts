import { ref, type ComputedRef, type Ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getPageTextStatus, getPageTextTask, rebuildPageText, reextractPage } from '@/api/vision'
import type { BookDetail } from '@/types'

export interface PageCacheStatusData {
  total: number
  cached: number
}

export interface ReaderPageCache {
  pageCacheStatus: Ref<PageCacheStatusData | null>
  pageCacheBusy: Ref<boolean>
  refreshPageCacheStatus: () => Promise<void>
  reExtractCurrentPage: () => Promise<void>
  rebuildPageCache: () => Promise<void>
  dispose: () => void
}

/** PDF 页缓存（M7 多模态视觉提取）：覆盖状态、重提本页、后台重建任务轮询。 */
export function useReaderPageCache(opts: {
  bookId: ComputedRef<number>
  book: Ref<BookDetail | null>
  pageIndex: Ref<number | null>
}): ReaderPageCache {
  const { bookId, book, pageIndex } = opts
  const pageCacheStatus = ref<PageCacheStatusData | null>(null)
  const pageCacheBusy = ref(false)

  async function refreshPageCacheStatus(bookIdArg?: number) {
    // 审查 I-2：支持按指定书刷新（重建轮询终态用任务快照书，切书后不串台）
    const bid = bookIdArg ?? bookId.value
    if (book.value?.format !== 'pdf' || !bid) {
      pageCacheStatus.value = null
      return
    }
    try {
      pageCacheStatus.value = await getPageTextStatus(bid)
    } catch {
      pageCacheStatus.value = null
    }
  }

  async function reExtractCurrentPage() {
    if (pageIndex.value == null || !book.value) return
    const targetBookId = bookId.value // 审查 I-2：快照书/页，切书后迟到响应不误写
    const targetPage = pageIndex.value
    pageCacheBusy.value = true
    try {
      await reextractPage(targetBookId, targetPage)
      if (disposed) return
      ElMessage.success(`第 ${targetPage} 页已重新提取`)
    } catch (err) {
      if (disposed) return
      ElMessage.error(err instanceof Error ? err.message : String(err))
    } finally {
      if (disposed) return
      pageCacheBusy.value = false
      await refreshPageCacheStatus()
    }
  }

  async function rebuildPageCache() {
    if (!book.value) return
    if (pageCacheBusy.value) return // I-15 修复：入口防重守卫（按钮 loading 之外的兜底）
    try {
      await ElMessageBox.confirm(
        '将重建本书全部页缓存（多模态逐页提取，可能耗时较长）。是否继续？',
        '重建页缓存',
        { type: 'warning' },
      )
    } catch {
      return
    }
    pageCacheBusy.value = true
    const taskBookId = bookId.value // I-15 修复：bookId 快照，轮询期间切换书籍不误查
    try {
      const { task_id } = await rebuildPageText(taskBookId, true)
      if (disposed) return // 审查：卸载后响应到达不再启动轮询（提交在途竞态）
      ElMessage.success('已提交重建任务，完成后自动刷新')
      pollTaskId = task_id
      pollBookId = taskBookId
      startPolling()
    } catch (err) {
      if (disposed) return
      pageCacheBusy.value = false
      ElMessage.error(err instanceof Error ? err.message : String(err))
    }
  }

  /** 卸载清理（审查 N-2）：停止重建轮询并移除可见性监听。 */
  function dispose() {
    disposed = true
    stopPolling()
    pollTaskId = null
    pollBookId = null
    pageCacheBusy.value = false
  }

  /* ---------- 重建任务轮询（页面可见性感知：隐藏/最小化时暂停 2s 轮询，恢复后继续） ---------- */
  let pollTimer: number | null = null
  let pollTaskId: string | null = null
  // 审查 I-15：bookId 快照提升为实例字段——可见性恢复路径（onTaskPollVisibility→startPolling）
  // 必须用启动时的书，而不是当前书（否则切书+切标签页组合会查错书并静默丢失任务）。
  let pollBookId: number | null = null
  let disposed = false // 审查：卸载后置位，提交在途的响应到达时不再启动轮询

  /** 只停定时器（审查 N-1）：可见性隐藏时调用，保留监听器以便恢复可见时重新开始轮询。 */
  function pausePolling() {
    if (pollTimer != null) {
      window.clearInterval(pollTimer)
      pollTimer = null
    }
  }

  /** 任务终态清理：停定时器并移除可见性监听器。 */
  function stopPolling() {
    pausePolling()
    document.removeEventListener('visibilitychange', onTaskPollVisibility)
  }

  function startPolling() {
    if (pollTimer != null || !pollTaskId || pollBookId == null) return
    const taskId = pollTaskId
    const snapshotBookId = pollBookId
    document.addEventListener('visibilitychange', onTaskPollVisibility)
    pollTimer = window.setInterval(async () => {
      try {
        const st = await getPageTextTask(snapshotBookId, taskId)
        if (st.status === 'success' || st.status === 'failed') {
          stopPolling()
          pollTaskId = null
          pageCacheBusy.value = false
          if (st.status === 'failed') ElMessage.error(`重建失败：${st.error || '未知错误'}`)
          // 审查 I-2：按任务快照书刷新——用户已切书时不得用旧书状态覆盖新书状态
          if (bookId.value === snapshotBookId) await refreshPageCacheStatus(snapshotBookId)
        }
      } catch {
        stopPolling()
        pollTaskId = null
        pageCacheBusy.value = false
      }
    }, 2000)
  }

  function onTaskPollVisibility() {
    if (document.visibilityState === 'visible') startPolling()
    else pausePolling()
  }

  return {
    pageCacheStatus,
    pageCacheBusy,
    refreshPageCacheStatus,
    reExtractCurrentPage,
    rebuildPageCache,
    dispose,
  }
}
