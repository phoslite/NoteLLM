import { ref, type Ref } from 'vue'

export interface SelMenuState {
  visible: boolean
  text: string
  top: number
  left: number
  /** 选区锚点所在段落下标（用于高亮失败时回退整段高亮）。 */
  paraIdx: number | null
}

export interface ReaderSelection {
  selMenu: Ref<SelMenuState>
  onMouseUp: (e: MouseEvent) => void
  onDocMouseDown: (e: MouseEvent) => void
  closeSelMenu: () => void
  /** 取走当前划词文本并关闭菜单、清除选区；无划词返回空串。 */
  takeSelection: () => string
}

/** 从选区锚点向上找 [data-para] 段落下标（选区横跨多段时取锚点所在段）。 */
function paraIndexFromSelection(sel: Selection): number | null {
  const anchor = sel.anchorNode
  if (!anchor) return null
  const el = anchor.nodeType === 1 ? (anchor as Element) : (anchor.parentElement as Element | null)
  const paraEl = el?.closest?.('[data-para]') ?? null
  if (!paraEl) return null
  const idx = Number(paraEl.getAttribute('data-para'))
  return Number.isFinite(idx) ? idx : null
}

/**
 * 阅读区划词菜单：定位、显示/隐藏、取走选区文本。
 * @param container 阅读正文滚动容器
 * @param menuEl 划词菜单的模板 ref（多实例安全；不再 document.querySelector）
 */
export function useReaderSelection(
  container: Ref<HTMLElement | null>,
  menuEl: Ref<HTMLElement | null>,
): ReaderSelection {
  const selMenu = ref<SelMenuState>({ visible: false, text: '', top: 0, left: 0, paraIdx: null })

  function onMouseUp(_e: MouseEvent) {
    const sel = window.getSelection()
    const text = sel?.toString().trim() ?? ''
    if (!sel || !sel.rangeCount || !text) {
      selMenu.value.visible = false
      return
    }
    const el = container.value
    if (!el || !sel.anchorNode || !el.contains(sel.anchorNode)) {
      selMenu.value.visible = false
      return
    }
    const rect = sel.getRangeAt(0).getBoundingClientRect()
    selMenu.value = {
      visible: true,
      text,
      top: Math.max(8, rect.bottom + 6),
      left: Math.max(8, rect.left),
      paraIdx: paraIndexFromSelection(sel),
    }
    // I-10 修复：菜单为 flex 实宽（约 520px），按实际渲染宽度钳制，防止右侧出屏
    requestAnimationFrame(() => {
      const menu = menuEl.value
      if (!menu) return
      const width = menu.offsetWidth || 520
      const maxLeft = window.innerWidth - width - 8
      if (selMenu.value.left > maxLeft) selMenu.value.left = Math.max(8, maxLeft)
    })
  }

  function onDocMouseDown(e: MouseEvent) {
    const menu = menuEl.value
    if (menu && !menu.contains(e.target as Node)) selMenu.value.visible = false
  }

  function closeSelMenu() {
    selMenu.value.visible = false
    window.getSelection()?.removeAllRanges()
  }

  function takeSelection(): string {
    const text = selMenu.value.text
    closeSelMenu()
    return text
  }

  return { selMenu, onMouseUp, onDocMouseDown, closeSelMenu, takeSelection }
}
