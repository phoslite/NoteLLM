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

  async function refreshPageCacheStatus() {
    if (book.value?.format !== 'pdf' || !bookId.value) {
      pageCacheStatus.value = null
      return
    }
    try {
      pageCacheStatus.value = await getPageTextStatus(bookId.value)
    } catch {
      pageCacheStatus.value = null
    }
  }

  async function reExtractCurrentPage() {
    if (pageIndex.value == null || !book.value) return
    pageCacheBusy.value = true
    try {
      await reextractPage(bookId.value, pageIndex.value)
      ElMessage.success(`第 ${pageIndex.value} 页已重新提取`)
    } catch (err) {
      ElMessage.error((err as Error).message)
    } finally {
      pageCacheBusy.value = false
      await refreshPageCacheStatus()
    }
  }

  async function rebuildPageCache() {
    if (!book.value) return
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
    try {
      const { task_id } = await rebuildPageText(bookId.value, true)
      ElMessage.success('已提交重建任务，完成后自动刷新')
      pollTaskId = task_id
      startPolling()
    } catch (err) {
      pageCacheBusy.value = false
      ElMessage.error((err as Error).message)
    }
  }

  /** 卸载清理（审查 N-2）：停止重建轮询并移除可见性监听。 */
  function dispose() {
    stopPolling()
    pollTaskId = null
    pageCacheBusy.value = false
  }

  /* ---------- 重建任务轮询（页面可见性感知：隐藏/最小化时暂停 2s 轮询，恢复后继续） ---------- */
  let pollTimer: number | null = null
  let pollTaskId: string | null = null

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
    if (pollTimer != null || !pollTaskId) return
    const taskId = pollTaskId
    document.addEventListener('visibilitychange', onTaskPollVisibility)
    pollTimer = window.setInterval(async () => {
      try {
        const st = await getPageTextTask(bookId.value, taskId)
        if (st.status === 'success' || st.status === 'failed') {
          stopPolling()
          pollTaskId = null
          pageCacheBusy.value = false
          if (st.status === 'failed') ElMessage.error(`重建失败：${st.error || '未知错误'}`)
          await refreshPageCacheStatus()
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
