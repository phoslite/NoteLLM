import { nextTick, ref, watch, type ComputedRef, type Ref } from 'vue'
import { getPageAnnotations, savePageAnnotations } from '@/api/annotations'
import type { AnnotationElement } from '@/types'
import { normalizeAnnotationPoints } from '@/utils/annotations'
import PageDoodleCanvas from '@/components/PageDoodleCanvas.vue'

export interface CropAskPayload {
  element: AnnotationElement
  bbox: [number, number, number, number]
  dataUrl: string
}

export interface ReaderDoodle {
  doodleElements: Ref<AnnotationElement[]>
  doodleTool: Ref<'pen' | 'highlight' | 'eraser' | 'text'>
  doodleColor: Ref<string>
  doodleLineWidth: Ref<number>
  doodleCanvasRef: Ref<InstanceType<typeof PageDoodleCanvas> | null>
  doodleCanUndo: Ref<boolean>
  doodleNoteDialog: Ref<{ visible: boolean; index: number; text: string }>
  pageDisplaySize: Ref<{ w: number; h: number }>
  onPageImgResize: () => void
  loadDoodle: (page: number) => Promise<void>
  scheduleDoodleSave: () => void
  onDoodleEditNote: (el: AnnotationElement) => void
  saveDoodleNote: () => void
  askCropOnDoodle: (payload: CropAskPayload) => void
  /** 页码切换：保存上一页涂鸦、清空画板并加载新页涂鸦。 */
  switchPage: (prevPageMode: boolean, prevPage: number | null, nextPage: number | null) => Promise<void>
  dispose: () => void
}

/** PDF 页图涂鸦：画板状态、按页加载/防抖保存、划线批注与划线区域提问。 */
export function useReaderDoodle(opts: {
  bookId: ComputedRef<number>
  pageIndex: Ref<number | null>
  /** 划线区域提问回调（由 AI 助手注入问题并发送裁剪图）。 */
  onAskCrop: (question: string, crop: { crop_image?: string; crop_label?: string }) => void
}): ReaderDoodle {
  const { bookId, pageIndex, onAskCrop } = opts

  const doodleElements = ref<AnnotationElement[]>([])
  const doodleTool = ref<'pen' | 'highlight' | 'eraser' | 'text'>('pen')
  const doodleColor = ref('#e74c3c')
  const doodleLineWidth = ref(3)
  const doodleCanvasRef = ref<InstanceType<typeof PageDoodleCanvas> | null>(null)
  const doodleCanUndo = ref(false)
  const doodleNoteDialog = ref<{ visible: boolean; index: number; text: string }>({ visible: false, index: -1, text: '' })
  const pageDisplaySize = ref({ w: 0, h: 0 })
  let doodleSaveTimer: ReturnType<typeof setTimeout> | null = null
  let doodleLoadedPage: number | null = null

  /** 页图渲染尺寸（画板叠加坐标基准）。 */
  function onPageImgResize() {
    const img = document.querySelector('.page-img') as HTMLImageElement | null
    if (img) {
      pageDisplaySize.value = { w: img.clientWidth, h: img.clientHeight }
    }
  }

  async function loadDoodle(page: number) {
    if (doodleLoadedPage === page) return
    doodleLoadedPage = page
    try {
      doodleElements.value = normalizeAnnotationPoints(await getPageAnnotations(bookId.value, page))
    } catch {
      doodleElements.value = []
    }
  }

  function scheduleDoodleSave() {
    if (doodleLoadedPage == null) return
    if (doodleSaveTimer) clearTimeout(doodleSaveTimer)
    doodleSaveTimer = setTimeout(() => {
      void savePageAnnotations(bookId.value, doodleLoadedPage!, doodleElements.value).catch(() => {
        /* 保存失败静默，下次改动重试 */
      })
    }, 800)
  }

  function onDoodleEditNote(el: AnnotationElement) {
    const idx = doodleElements.value.indexOf(el)
    if (idx < 0) return
    doodleNoteDialog.value = { visible: true, index: idx, text: el.note ?? '' }
  }

  function saveDoodleNote() {
    const d = doodleNoteDialog.value
    if (d.index < 0) return
    const item = doodleElements.value[d.index]
    if (item) {
      item.note = d.text
      item.note_meta = { created_at: item.note_meta?.created_at ?? new Date().toISOString(), updated_at: new Date().toISOString() }
    }
    d.visible = false
    scheduleDoodleSave()
  }

  /** 划线区域提问：把裁剪图交给 AI 助手。 */
  function askCropOnDoodle(payload: CropAskPayload) {
    const [x1, y1, x2, y2] = payload.bbox
    const question = `请解读我在第 ${pageIndex.value} 页划线的这部分内容，引用须标注出处：`
    const crop = {
      crop_image: payload.dataUrl || undefined,
      crop_label: `第 ${pageIndex.value} 页，区域 ${(x1 * 100).toFixed(0)}%~${(x2 * 100).toFixed(0)}%（横向），${(y1 * 100).toFixed(0)}%~${(y2 * 100).toFixed(0)}%（纵向）`,
    }
    onAskCrop(question, crop)
  }

  async function switchPage(prevPageMode: boolean, prevPage: number | null, nextPage: number | null): Promise<void> {
    // 切页前保存上一页涂鸦
    if (prevPageMode && prevPage != null && prevPage !== nextPage) {
      void savePageAnnotations(bookId.value, prevPage, doodleElements.value).catch(() => {})
      doodleElements.value = []
      doodleLoadedPage = null
    }
    if (nextPage != null) {
      await loadDoodle(nextPage)
    }
  }

  function dispose() {
    if (doodleSaveTimer) clearTimeout(doodleSaveTimer)
    doodleSaveTimer = null
    doodleLoadedPage = null
  }

  watch(doodleElements, () => {
    scheduleDoodleSave()
  }, { deep: true })

  watch(pageIndex, (v) => {
    if (v != null) {
      doodleCanvasRef.value?.resetUndo()
      void nextTick(onPageImgResize)
    }
  })

  return {
    doodleElements, doodleTool, doodleColor, doodleLineWidth, doodleCanvasRef,
    doodleCanUndo, doodleNoteDialog, pageDisplaySize,
    onPageImgResize, loadDoodle, scheduleDoodleSave, onDoodleEditNote,
    saveDoodleNote, askCropOnDoodle, switchPage, dispose,
  }
}
