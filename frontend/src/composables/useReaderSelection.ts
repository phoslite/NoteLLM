import { ref, type Ref } from 'vue'

export interface SelMenuState {
  visible: boolean
  text: string
  top: number
  left: number
}

export interface ReaderSelection {
  selMenu: Ref<SelMenuState>
  onMouseUp: (e: MouseEvent) => void
  onDocMouseDown: (e: MouseEvent) => void
  closeSelMenu: () => void
  /** 取走当前划词文本并关闭菜单、清除选区；无划词返回空串。 */
  takeSelection: () => string
}

/** 阅读区划词菜单：定位、显示/隐藏、取走选区文本。 */
export function useReaderSelection(container: Ref<HTMLElement | null>): ReaderSelection {
  const selMenu = ref<SelMenuState>({ visible: false, text: '', top: 0, left: 0 })

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
      left: Math.min(Math.max(8, rect.left), window.innerWidth - 280),
    }
  }

  function onDocMouseDown(e: MouseEvent) {
    const menu = document.querySelector('.sel-menu')
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
