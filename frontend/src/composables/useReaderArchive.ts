import { ref, type ComputedRef, type Ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { archiveBook } from '@/api/rag'
import { notifyTaskSubmitted } from '@/utils/task'
import { TASK_TIMEOUT_MS } from '@/utils/constants'
import { useTaskPoll } from './useTaskPoll'
import type { BookDetail } from '@/types'

export interface ReaderArchive {
  archiving: Ref<boolean>
  archiveAndSummarize: () => Promise<void>
  dispose: () => void
}

/** 读完归档（M9）：确认后提交归档任务并轮询，结束后刷新书籍与书架。 */
export function useReaderArchive(opts: {
  bookId: ComputedRef<number>
  book: Ref<BookDetail | null>
  onDone: () => Promise<void>
}): ReaderArchive {
  const { bookId, book, onDone } = opts
  const archiving = ref(false)
  // 四轮 m1：轮询收敛 useTaskPoll（卸载由其上顶层 onBeforeUnmount 自动中止，替代手写 AbortController）
  const poll = useTaskPoll()

  async function archiveAndSummarize() {
    if (!book.value) return
    try {
      await ElMessageBox.confirm(
        '将整本书归档：标记读完，并总结为 RAG/Skill 资产（PDF 书籍仅对未建立缓存的页面执行视觉提取，已缓存页直接复用）。继续？',
        '归档并总结',
        { type: 'info', confirmButtonText: '归档' },
      )
    } catch {
      return
    }
    archiving.value = true
    // 快照守卫（四轮 m1）：提交时的书 id——切书后迟到的完成回调不刷新新书视图
    const submittedBookId = bookId.value
    try {
      const { task_id } = await archiveBook(submittedBookId)
      ElMessage.info('归档任务已提交，正在总结…')
      notifyTaskSubmitted()
      // 审查 B-4：轮询收敛到 utils/task.ts::waitForTask（原 120 次 × 1.5s = 180s 超时保持一致）
      const st = await poll.run(task_id, { intervalMs: 1500, timeoutMs: TASK_TIMEOUT_MS })
      if (st.status === 'failed') {
        ElMessage.error(`归档失败：${st.error || '未知错误'}`)
      } else {
        ElMessage.success('归档完成：RAG/Skill 资产已生成')
      }
      if (bookId.value === submittedBookId) await onDone()
    } catch (err) {
      if ((err as Error).name === 'AbortError') return
      const msg = (err as Error).message
      if (msg.includes('超时')) ElMessage.warning('归档任务超时，请稍后在资料页查看资产状态')
      else ElMessage.error(msg)
    } finally {
      archiving.value = false
    }
  }

  /** 卸载清理（审查 N-10）：轮询中止已由 useTaskPoll 顶层 onBeforeUnmount 处理，保留接口兼容。 */
  function dispose() {
    /* no-op：useTaskPoll 顶层注册 onBeforeUnmount */
  }

  return { archiving, archiveAndSummarize, dispose }
}