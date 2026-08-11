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
  let doodleBookId: number | null = null  // 终审 §6.9：涂鸦所属书快照（跨书守卫，防切书串写）
  let doodleLoading = false  // F8：页涂鸦 fetch 在途标记（切页空数组临时态不触发保存）
  let doodleReadyPage: number | null = null  // F8：已成功加载到内存的页（未就绪不即时保存，防空数组覆盖）
  let doodleDirty = false // 三审 Minor-3：脏标记——仅用户改动后落盘，只读访问不再回写
  let doodleSuppressSave = false // 三审 Minor-3：服务端加载赋值期间抑制 deep-watch 误判（watch 回调异步执行时 doodleLoading 已复位）

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
    doodleBookId = bookId.value  // 终审 §6.9：加载时快照所属书
    doodleLoading = true
    try {
      const items = normalizeAnnotationPoints(await getPageAnnotations(doodleBookId, page))
      if (doodleLoadedPage !== page) return  // F8：fetch 迟到响应丢弃，防跨页错写
      if (doodleBookId !== bookId.value) return  // 终审 §6.9：切书后迟到响应丢弃（跨书守卫）
      if (doodleElements.value.length > 0) {
        // 审查 I-2：加载在途用户已绘制 → 保留本地绘制不覆盖，服务端数据下次进入该页再载
        doodleReadyPage = page
        doodleDirty = true // 加载在途用户已绘制：标记脏，落盘本地绘制（加载期 watch 被 loading 跳过）
        scheduleDoodleSave()
        return
      }
      doodleSuppressSave = true // 三审 Minor-3：服务端加载赋值：抑制 deep-watch（回调异步执行时 loading 已复位）
      doodleElements.value = items
      doodleDirty = false // 服务端加载态 = 干净
      doodleReadyPage = page
      void nextTick(() => { doodleSuppressSave = false })
    } catch {
      if (doodleLoadedPage === page && doodleElements.value.length === 0) {
        doodleSuppressSave = true // 服务端加载赋值：抑制 deep-watch（回调异步执行时 loading 已复位）
        doodleElements.value = []
        doodleReadyPage = page  // 加载失败视为已就绪（空画板），避免后续误存旧页数据
        void nextTick(() => { doodleSuppressSave = false })
      } else if (doodleLoadedPage === page) {
        doodleReadyPage = page  // 加载失败但用户已绘制：保留绘制并视为就绪
      }
    } finally {
      // 终审 §6.9：迟到响应无条件复位 loading（否则切到无页章节后 loading 永久卡死，后续涂鸦不再保存）
      doodleLoading = false
    }
  }

  function scheduleDoodleSave() {
    if (doodleSaveTimer) clearTimeout(doodleSaveTimer)
    doodleSaveTimer = null
    if (doodleLoadedPage == null) return
    // F8 修复：快照调度时刻的页码与元素，避免定时器触发时读到下一页/空数组
    const wasDirty = doodleDirty // 三审 Minor-3：仅脏时落盘
    const page = doodleLoadedPage
    const elements = [...doodleElements.value]
    const savedBookId = bookId.value  // 终审 §6.9：书级快照（定时器触发时可能已切书）
    doodleSaveTimer = setTimeout(() => {
      if (!wasDirty) return  // 三审 Minor-3：快照非脏不落盘（只读访问零写请求）
      if (doodleLoadedPage !== page) return  // 期间又切页：旧页数据由 switchPage 即时保存负责
      if (bookId.value !== savedBookId) return  // 终审 §6.9：切书后旧书数据不写入新书
      void savePageAnnotations(savedBookId, page, elements)
        .then(() => { if (doodleLoadedPage === page) doodleDirty = false })
        .catch(() => {
          /* 保存失败静默，脏标记保留，下次改动重试 */
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
    doodleDirty = true
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
    // 切页前保存上一页涂鸦（F8：仅当该页数据已就绪才保存，防空数组覆盖服务端涂鸦）
    if (prevPageMode && prevPage != null && prevPage !== nextPage) {
      if (doodleReadyPage === prevPage && bookId.value === doodleBookId && doodleDirty) {
        void savePageAnnotations(doodleBookId, prevPage, doodleElements.value).catch(() => {})
      }
      // 未就绪（fetch 在途）：丢弃内存临时态即可，服务端数据无损
      doodleElements.value = []
      doodleLoadedPage = null
      doodleReadyPage = null
      doodleDirty = false // 画布已清空复位
    }
    if (nextPage != null) {
      await loadDoodle(nextPage)
    }
  }

  function dispose() {
    // 终审 §6.9：书级守卫——路由重挂载时 bookId 已指向新书，旧书涂鸦不得写入新书（C1 数据损坏修复）
    if (doodleReadyPage != null && bookId.value === doodleBookId && doodleDirty) {
      // F17 修复：卸载前 flush 未落盘的防抖改动，防 ≤800ms 涂鸦丢失
      void savePageAnnotations(doodleBookId, doodleReadyPage, doodleElements.value).catch(() => {})
    }
    if (doodleSaveTimer) clearTimeout(doodleSaveTimer)
    doodleSaveTimer = null
    doodleLoadedPage = null
    stopElementsWatch() // 审查 I-2：dispose 后 watcher 同步停止
    stopPageIndexWatch()
  }

  const stopElementsWatch = watch(doodleElements, () => {
    if (doodleLoading) return  // F8：切页/加载期间的空数组临时态不触发保存
    if (doodleSuppressSave) return  // 三审 Minor-3：服务端加载赋值不触发保存
    doodleDirty = true // 三审 Minor-3：用户改动标记脏
    scheduleDoodleSave()
  }, { deep: true })

  const stopPageIndexWatch = watch(pageIndex, (v) => {
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