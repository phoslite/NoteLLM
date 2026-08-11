import { nextTick, ref, watch, type ComputedRef, type Ref } from 'vue'
import { generateMindmap } from '@/api/mindmap'
import type { ChapterItem, MindMapResult } from '@/types'

export interface ReaderMindmap {
  mindmapOpen: Ref<boolean>
  mindmapLoading: Ref<boolean>
  mindmapError: Ref<string>
  mindmapData: Ref<MindMapResult | null>
  openMindmap: (selection?: string) => Promise<void>
  jumpToMindmapPos: (pos: { chapter: number; para: string }) => void
}

/** 脑图：基于当前章节生成知识结构树，支持从划词段落生成；点击节点跳回正文。 */
export function useReaderMindmap(opts: {
  bookId: ComputedRef<number>
  currentChapterId: Ref<number | null>
  chapters: ComputedRef<ChapterItem[]>
  scrollEl: Ref<HTMLElement | null>
  closeSelection: () => void
  loadChapter: (chapterId: number, restore: boolean) => Promise<void>
}): ReaderMindmap {
  const { bookId, currentChapterId, chapters, scrollEl, closeSelection, loadChapter } = opts
  const mindmapOpen = ref(false)
  const mindmapLoading = ref(false)
  const mindmapError = ref('')
  const mindmapData = ref<MindMapResult | null>(null)
  let mindmapSeq = 0 // I-14 修复：请求序号守卫，丢弃旧章节的迟到响应

  // 审查 I-2：切章（未重开脑图）时自增代际——旧章节的迟到响应不得写入新章节视图
  watch(currentChapterId, () => {
    mindmapSeq += 1
    if (mindmapOpen.value) {
      mindmapOpen.value = false
      mindmapData.value = null
    }
  })

  async function openMindmap(selection?: string) {
    if (!currentChapterId.value) return
    const seq = ++mindmapSeq
    closeSelection()
    mindmapOpen.value = true
    mindmapLoading.value = true
    mindmapError.value = ''
    mindmapData.value = null
    try {
      const data = await generateMindmap(bookId.value, {
        chapter_id: currentChapterId.value,
        selection: selection || undefined,
      })
      if (seq !== mindmapSeq) return // 已有更新的请求，丢弃本次结果
      mindmapData.value = data
    } catch (err) {
      if (seq !== mindmapSeq) return
      mindmapError.value = (err as Error).message
    } finally {
      if (seq === mindmapSeq) mindmapLoading.value = false
    }
  }

  function jumpToMindmapPos(pos: { chapter: number; para: string }) {
    const chapter = chapters.value.find((c) => c.index === pos.chapter)
    mindmapOpen.value = false
    if (!chapter) return
    const go = () =>
      nextTick(() => {
        const target = scrollEl.value?.querySelector(`[data-para="${pos.para}"]`) as HTMLElement | null
        target?.scrollIntoView({ block: 'start' })
      })
    if (chapter.id !== currentChapterId.value) {
      void loadChapter(chapter.id, false).then(go)
    } else {
      void go()
    }
  }

  return { mindmapOpen, mindmapLoading, mindmapError, mindmapData, openMindmap, jumpToMindmapPos }
}
