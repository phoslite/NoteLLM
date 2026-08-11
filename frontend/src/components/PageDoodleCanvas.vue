<template>
  <div class="doodle-wrap" :style="wrapStyle">
    <!-- 页图（由外部渲染），画板叠加其上 -->
    <slot name="image" />
    <canvas
      ref="canvasEl"
      class="doodle-canvas"
      @pointerdown="onPointerDown"
      @pointermove="onPointerMove"
      @pointerup="onPointerUp"
      @click="onCanvasClick"
      @contextmenu.prevent
    />
    <!-- 划线选中操作菜单 -->
    <div
      v-if="menu.visible"
      class="doodle-menu"
      :style="{ top: menu.top + 'px', left: menu.left + 'px' }"
      @mousedown.stop
    >
      <button type="button" class="mini-btn" @click="editNote()">💬 批注</button>
      <button type="button" class="mini-btn ai" @click="askCrop()">🤖 就此划线提问</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import type { AnnotationElement } from '@/types'
import { normalizeAnnotationPoints, toPoint } from '@/utils/annotations'

const props = withDefaults(
  defineProps<{
    /** 画板可见区域（页图渲染后的 CSS 尺寸，px）。 */
    width: number
    height: number
    /** 涂鸦元素（相对页宽高的 0~1 归一化）。 */
    modelValue: AnnotationElement[]
    /** 当前工具。 */
    tool?: 'pen' | 'highlight' | 'eraser' | 'text'
    color?: string
    lineWidth?: number
    fontSize?: number
    /** 是否显示画板（仅 PDF 按页阅读时）。 */
    active?: boolean
  }>(),
  { tool: 'pen', color: '#e74c3c', lineWidth: 3, fontSize: 18, active: true },
)

const emit = defineEmits<{
  (e: 'update:modelValue', v: AnnotationElement[]): void
  /** 用户请求对划线区域提问（参数为划线元素的归一化 bbox 与裁剪 data URI）。 */
  (e: 'ask-crop', payload: { element: AnnotationElement; bbox: [number, number, number, number]; dataUrl: string }): void
  /** 用户请求编辑某元素批注（父组件弹窗）。 */
  (e: 'edit-note', element: AnnotationElement): void
  /** 撤销栈可用状态变化（供工具栏禁用/启用撤销按钮）。 */
  (e: 'can-undo', v: boolean): void
}>()

const canvasEl = ref<HTMLCanvasElement | null>(null)
const canvasSize = ref({ w: 1, h: 1 })

const wrapStyle = computed<Record<string, string>>(() => ({ display: 'inline-block', position: 'relative', lineHeight: '0' }))
const isEraser = computed(() => props.tool === 'eraser')
const isText = computed(() => props.tool === 'text')

/* ---------- 内部状态 ---------- */
let ctx: CanvasRenderingContext2D | null = null
let drawing = false
let currentStroke: AnnotationElement | null = null
let lastPoint: { x: number; y: number } | null = null
let lastDrawAt = 0
const undoStack: AnnotationElement[][] = []
const canUndo = ref(false)

const menu = ref<{ visible: boolean; top: number; left: number; index: number }>({
  visible: false,
  top: 0,
  left: 0,
  index: -1,
})

function syncCanUndo() {
  const v = undoStack.length > 0
  if (canUndo.value !== v) {
    canUndo.value = v
    emit('can-undo', v)
  }
}

function ensureCtx() {
  if (ctx || !canvasEl.value) return
  ctx = canvasEl.value.getContext('2d')
  syncSize()
}

/** 同步画板尺寸：以页图实际渲染尺寸为基准（旧数据点兼容在绘制层处理）。 */
function syncSize() {
  const el = canvasEl.value
  if (!el) return
  const img = (el.parentElement?.querySelector('img') || document.querySelector('.page-img')) as HTMLImageElement | null
  const rect = img?.getBoundingClientRect()
  const w = Math.max(1, Math.round(rect && rect.width > 0 ? rect.width : props.width || 1))
  const h = Math.max(1, Math.round(rect && rect.height > 0 ? rect.height : props.height || 1))
  const dpr = window.devicePixelRatio || 1
  canvasSize.value = { w, h }
  // 仅在缓冲区尺寸实际变化时重置（否则会清空已绘制内容）
  if (el.width !== Math.round(w * dpr) || el.height !== Math.round(h * dpr)) {
    el.width = Math.round(w * dpr)
    el.height = Math.round(h * dpr)
    ctx?.setTransform(dpr, 0, 0, dpr, 0, 0)
  }
  el.style.width = `${w}px`
  el.style.height = `${h}px`
}

function redraw() {
  const c = ctx
  const el = canvasEl.value
  if (!c || !el) return
  const w = canvasSize.value.w
  const h = canvasSize.value.h
  c.clearRect(0, 0, w, h)
  for (const item of props.modelValue) {
    if (item.type === 'stroke' && item.points?.length) {
      drawStroke(c, item, w, h, false)
    } else if (item.type === 'text' && item.text) {
      drawText(c, item, w, h)
    }
  }
  if (currentStroke && currentStroke.points?.length) {
    drawStroke(c, currentStroke, w, h, true)
  }
}

function drawStroke(c: CanvasRenderingContext2D, item: AnnotationElement, w: number, h: number, live: boolean) {
  const pts = item.points ?? []
  const lw = (item.line_width ?? 3) * (Math.max(w, h) / 1000)
  c.save()
  c.lineCap = 'round'
  c.lineJoin = 'round'
  c.lineWidth = lw
  if (item.tool === 'highlight') {
    c.globalAlpha = live ? 0.35 : 0.4
    c.strokeStyle = item.color ?? '#ffd666'
    c.lineWidth = lw * 5
  } else {
    c.globalAlpha = live ? 0.9 : 1
    c.strokeStyle = item.color ?? '#e74c3c'
  }
  c.beginPath()
  pts.forEach((p, i) => {
    const [x, y] = toPoint(p)
    const px = x * w
    const py = y * h
    if (i === 0) c.moveTo(px, py)
    else c.lineTo(px, py)
  })
  c.stroke()
  c.restore()
}

function drawText(c: CanvasRenderingContext2D, item: AnnotationElement, w: number, h: number) {
  c.save()
  c.fillStyle = item.color ?? '#333333'
  c.font = `${Math.round((item.font_size ?? 18) * (Math.max(w, h) / 1000))}px sans-serif`
  c.fillText(item.text ?? '', (item.x ?? 0) * w, (item.y ?? 0) * h)
  c.restore()
}

/* ---------- 指针绘制 ---------- */
function toNorm(e: PointerEvent): [number, number] {
  const rect = canvasEl.value!.getBoundingClientRect()
  return [
    Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width)),
    Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height)),
  ]
}

function onPointerDown(e: PointerEvent) {
  if (!props.active || !ctx) return
  const p = toNorm(e)
  if (isEraser.value) {
    eraseAt(p)
    return
  }
  if (isText.value) {
    void inputTextAt(p)
    return
  }
  menu.value.visible = false
  drawing = true
  currentStroke = {
    type: 'stroke',
    tool: props.tool === 'highlight' ? 'highlight' : 'pen',
    color: props.color,
    line_width: props.lineWidth,
    points: [p],
  }
  lastPoint = { x: p[0], y: p[1] }
  canvasEl.value!.setPointerCapture(e.pointerId)
}

function onPointerMove(e: PointerEvent) {
  if (!drawing || !currentStroke) return
  const p = toNorm(e)
  const last = lastPoint ?? { x: p[0], y: p[1] }
  const dist = Math.hypot(p[0] - last.x, p[1] - last.y)
  if (dist > 0.004) {
    currentStroke.points!.push(p)
    lastPoint = { x: p[0], y: p[1] }
    redraw()
  }
}

function onPointerUp() {
  if (drawing && currentStroke) {
    pushUndo()
    const items = [...props.modelValue, currentStroke]
    emit('update:modelValue', items)
    currentStroke = null
    drawing = false
    lastPoint = null
    lastDrawAt = Date.now()
  }
}

function eraseAt(p: [number, number]) {
  const w = canvasSize.value.w
  const h = canvasSize.value.h
  const hitRadius = (props.lineWidth * Math.max(w, h) / 1000) * 3
  let idx = -1
  props.modelValue.forEach((item, i) => {
    if (idx >= 0) return
    if (item.type === 'stroke' && item.points?.length) {
      for (const raw of item.points) {
        const [x, y] = toPoint(raw)
        if (Math.hypot((x - p[0]) * w, (y - p[1]) * h) <= hitRadius) {
          idx = i
          break
        }
      }
    } else if (item.type === 'text' && item.x != null && item.y != null) {
      if (Math.hypot((item.x - p[0]) * w, (item.y - p[1]) * h) <= hitRadius) {
        idx = i
      }
    }
  })
  if (idx >= 0) {
    pushUndo()
    const items = props.modelValue.filter((_, i) => i !== idx)
    emit('update:modelValue', items)
  }
}

/* ---------- 划线选中与菜单 ---------- */
function onCanvasClick(e: MouseEvent) {
  if (isEraser.value || isText.value || drawing) return
  if (Date.now() - lastDrawAt < 250) return
  const p = toNorm(e as PointerEvent)
  const idx = hitStroke(p)
  if (idx < 0) {
    menu.value.visible = false
    return
  }
  const rect = canvasEl.value!.getBoundingClientRect()
  menu.value = { visible: true, top: e.clientY - rect.top + 8, left: e.clientX - rect.left, index: idx }
}

function hitStroke(p: [number, number]): number {
  const w = canvasSize.value.w
  const h = canvasSize.value.h
  const tol = 10
  for (let i = props.modelValue.length - 1; i >= 0; i--) {
    const item = props.modelValue[i]
    if (item.type === 'stroke' && item.points?.length) {
      for (const raw of item.points) {
        const [x, y] = toPoint(raw)
        if (Math.hypot((x - p[0]) * w, (y - p[1]) * h) <= tol) return i
      }
    } else if (item.type === 'text' && item.x != null && item.y != null) {
      if (Math.hypot((item.x - p[0]) * w, (item.y - p[1]) * h) <= 14) return i
    }
  }
  return -1
}

/* ---------- 撤销 ---------- */
function pushUndo() {
  undoStack.push(props.modelValue.map((x) => ({ ...x, points: x.points ? [...x.points] : undefined })))
  if (undoStack.length > 5) undoStack.shift()
  syncCanUndo()
}

function undo() {
  if (!undoStack.length) return
  const prev = undoStack.pop()!
  emit('update:modelValue', prev)
  menu.value.visible = false
  syncCanUndo()
}

/** 切换页面时清空撤销栈与选中菜单。 */
function resetUndo() {
  undoStack.length = 0
  syncCanUndo()
  menu.value.visible = false
}

/* ---------- 划线批注 / 提问 ---------- */
function selectedElement(): AnnotationElement | null {
  if (menu.value.index < 0) return null
  return props.modelValue[menu.value.index] ?? null
}

function editNote() {
  const el = selectedElement()
  if (!el) return
  emit('edit-note', el)
}

function bboxOf(el: AnnotationElement): [number, number, number, number] {
  if (el.type === 'stroke' && el.points?.length) {
    let minX = 1, minY = 1, maxX = 0, maxY = 0
    for (const raw of el.points) {
      const [x, y] = toPoint(raw)
      minX = Math.min(minX, x); minY = Math.min(minY, y)
      maxX = Math.max(maxX, x); maxY = Math.max(maxY, y)
    }
    return [minX, minY, maxX, maxY]
  }
  return [el.x ?? 0, el.y ?? 0, el.x ?? 0, el.y ?? 0]
}

function askCrop() {
  const el = selectedElement()
  if (!el) return
  menu.value.visible = false
  const bbox = bboxOf(el)
  // 裁剪页图（原图分辨率）→ data URI；图片元素或不可用时的 fallback bbox
  const img = (document.querySelector('.page-img') as HTMLImageElement | null) ?? null
  const dataUrl = cropDataUrl(img, bbox)
  emit('ask-crop', { element: el, bbox, dataUrl })
}

function cropDataUrl(img: HTMLImageElement | null, bbox: [number, number, number, number]): string {
  const canvas = document.createElement('canvas')
  const pad = 0.02
  const [minX, minY, maxX, maxY] = bbox
  const w = Math.max(1, Math.round((maxX - minX + pad * 2) * (img?.naturalWidth || 800)))
  const h = Math.max(1, Math.round((maxY - minY + pad * 2) * (img?.naturalHeight || 600)))
  canvas.width = w
  canvas.height = h
  const c = canvas.getContext('2d')
  if (!c) return ''
  if (img && img.complete && img.naturalWidth) {
    const sx = Math.max(0, (minX - pad) * img.naturalWidth)
    const sy = Math.max(0, (minY - pad) * img.naturalHeight)
    c.drawImage(img, sx, sy, w, h, 0, 0, w, h)
  }
  return canvas.toDataURL('image/jpeg', 0.85)
}

/* ---------- 文本输入：弹窗输入并写回 ---------- */
async function inputTextAt(p: [number, number]) {
  try {
    const { value } = await ElMessageBox.prompt('输入文本内容', '添加文本标注', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      inputValue: '',
    })
    const text = (value ?? '').trim()
    if (!text) return
    const el: AnnotationElement = { type: 'text', text, color: props.color, font_size: props.fontSize, x: p[0], y: p[1] }
    pushUndo()
    emit('update:modelValue', [...props.modelValue, el])
    redraw()
  } catch {
    /* 取消输入 */
  }
}

/* ---------- 生命周期 ---------- */
let resizeObs: ResizeObserver | null = null
let sizeRetryTimer: ReturnType<typeof setTimeout> | null = null

onMounted(() => {
  ensureCtx()
  syncSize()
  try {
    redraw()
  } catch (err) {
    // 渲染异常不阻塞画板初始化（旧数据格式兼容由 normalize 兜底）
    console.error('[PageDoodleCanvas] redraw failed:', err)
  }
  resizeObs = new ResizeObserver(() => {
    syncSize()
    redraw()
  })
  const img = canvasEl.value?.parentElement?.querySelector('img') as HTMLImageElement | null
  if (img) resizeObs.observe(img)
  if (canvasEl.value) resizeObs.observe(canvasEl.value)
  document.addEventListener('pointerup', onPointerUp as EventListener)
  // 兜底：页图异步加载完成后重试同步尺寸（最多 10 次，间隔 250ms）
  let tries = 0
  sizeRetryTimer = setInterval(() => {
    tries += 1
    const before = canvasSize.value
    syncSize()
    const changed = canvasSize.value.w !== before.w || canvasSize.value.h !== before.h
    if (canvasSize.value.w > 1 && !changed) {
      if (sizeRetryTimer) clearInterval(sizeRetryTimer)
      sizeRetryTimer = null
    } else {
      redraw()
    }
    if (tries >= 10 && sizeRetryTimer) {
      clearInterval(sizeRetryTimer)
      sizeRetryTimer = null
    }
  }, 250)
})

onBeforeUnmount(() => {
  resizeObs?.disconnect()
  if (sizeRetryTimer) clearInterval(sizeRetryTimer)
  document.removeEventListener('pointerup', onPointerUp as EventListener)
})

watch(() => [props.width, props.height], () => {
  syncSize()
  redraw()
})

watch(
  () => props.modelValue.length,
  () => {
    // 尺寸就绪后重绘（避免首帧 canvas 宽高为 1 时坐标错乱）
    if (canvasSize.value.w > 1) redraw()
  },
)

watch(
  () => props.modelValue,
  (v) => {
    // 旧版 {x,y} 对象点迁移为 [x,y]，避免渲染崩溃；迁移后回写父组件持久化
    const norm = normalizeAnnotationPoints(v)
    if (norm !== v) emit('update:modelValue', norm)
    redraw()
  },
  { deep: true },
)

defineExpose({ undo, resetUndo })
</script>

<style scoped>
.doodle-wrap { position: relative; }
.doodle-canvas {
  position: absolute;
  inset: 0;
  cursor: crosshair;
  touch-action: none;
}
.doodle-menu {
  position: absolute;
  z-index: 30;
  display: flex;
  gap: 4px;
  padding: 6px;
  background: #fff;
  border: 1px solid var(--border-color, #dcdfe6);
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
}
.mini-btn {
  border: 1px solid var(--border-color, #dcdfe6);
  background: #fff;
  color: var(--text-color, #303133);
  font-size: 13px;
  padding: 3px 8px;
  border-radius: 4px;
  cursor: pointer;
  white-space: nowrap;
  min-height: 24px;
}
.mini-btn:hover { border-color: var(--primary-color, #2f6fb0); color: var(--primary-color, #2f6fb0); }
.mini-btn.ai { color: var(--primary-color, #2f6fb0); }
</style>