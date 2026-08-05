import { ref, type ComputedRef, type Ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { archiveBook } from '@/api/rag'
import { notifyTaskSubmitted, waitForTask } from '@/utils/task'
import type { BookDetail } from '@/types'

export interface ReaderArchive {
  archiving: Ref<boolean>
  archiveAndSummarize: () => Promise<void>
}

/** 读完归档（M9）：确认后提交归档任务并轮询，结束后刷新书籍与书架。 */
export function useReaderArchive(opts: {
  bookId: ComputedRef<number>
  book: Ref<BookDetail | null>
  onDone: () => Promise<void>
}): ReaderArchive {
  const { bookId, book, onDone } = opts
  const archiving = ref(false)

  async function archiveAndSummarize() {
    if (!book.value) return
    try {
      await ElMessageBox.confirm(
        '将整本书归档：标记读完，并总结为 RAG/Skill 资产（PDF 书籍会先用视觉模型通读全书并缓存）。继续？',
        '归档并总结',
        { type: 'info', confirmButtonText: '归档' },
      )
    } catch {
      return
    }
    archiving.value = true
    try {
      const { task_id } = await archiveBook(bookId.value)
      ElMessage.info('归档任务已提交，正在总结…')
      notifyTaskSubmitted()
      // 审查 B-4：轮询收敛到 utils/task.ts::waitForTask（原 120 次 × 1.5s = 180s 超时保持一致）
      const st = await waitForTask(task_id, { intervalMs: 1500, timeoutMs: 180000 })
      if (st.status === 'failed') {
        ElMessage.error(`归档失败：${st.error || '未知错误'}`)
      } else {
        ElMessage.success('归档完成：RAG/Skill 资产已生成')
      }
      await onDone()
    } catch (err) {
      const msg = (err as Error).message
      if (msg.includes('超时')) ElMessage.warning('归档任务超时，请稍后在资料页查看资产状态')
      else ElMessage.error(msg)
    } finally {
      archiving.value = false
    }
  }

  return { archiving, archiveAndSummarize }
}
