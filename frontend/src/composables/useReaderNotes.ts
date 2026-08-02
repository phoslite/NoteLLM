import { nextTick, ref, watch, type ComputedRef, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createNote, deleteNote, updateNote } from '@/api/reading'
import type { ChapterItem, NoteItem, NoteType } from '@/types'
import type { ReaderSelection } from './useReaderSelection'

export interface NoteDialogState {
  visible: boolean
  type: NoteType
  quote: string
  text: string
  editingId: number | null
}

export interface ReaderNotes {
  notes: Ref<NoteItem[]>
  notesDrawer: Ref<boolean>
  noteDialog: Ref<NoteDialogState>
  setNotes: (list: NoteItem[]) => void
  applyHighlights: () => void
  addNote: (type: NoteType, quote: string, text: string) => Promise<void>
  quickNote: (paraIdx: number, type: NoteType) => void
  selNote: (type: NoteType) => void
  addThinkList: () => Promise<void>
  noteChapter: (n: NoteItem) => ChapterItem | undefined
  jumpToNote: (n: NoteItem) => Promise<void>
  editNote: (n: NoteItem) => void
  removeNote: (n: NoteItem) => Promise<void>
  saveNoteDialog: () => Promise<void>
  typeTag: (t: NoteType) => string
}

/** 笔记域：正文高亮、划词/侧边按钮记笔记、笔记抽屉与编辑对话框状态。 */
export function useReaderNotes(opts: {
  bookId: ComputedRef<number>
  scrollEl: Ref<HTMLElement | null>
  currentChapterId: Ref<number | null>
  chapters: ComputedRef<ChapterItem[]>
  blocks: Ref<string[]>
  selection: ReaderSelection
  /** 跳到其他章节（内部会先保存当前进度）。 */
  loadChapter: (chapterId: number, restore: boolean) => Promise<void>
}): ReaderNotes {
  const { bookId, scrollEl, currentChapterId, chapters, blocks, selection, loadChapter } = opts
  const notes = ref<NoteItem[]>([])
  const notesDrawer = ref(false)
  const noteDialog = ref<NoteDialogState>({ visible: false, type: '批注', quote: '', text: '', editingId: null })

  const NOTE_HL_CLASS: Record<NoteType, string> = {
    高亮: 'note-hl-highlight',
    不理解: 'note-hl-confuse',
    批注: 'note-hl-comment',
    思考: 'note-hl-think',
  }

  /** 在容器 DOM 文本中精确匹配 quote 并包裹 <mark>（支持跨文本节点）。 */
  function wrapQuoteInElement(el: HTMLElement, quote: string, cls: string): boolean {
    if (!quote) return false
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
    const nodes: Text[] = []
    let full = ''
    let node: Node | null
    while ((node = walker.nextNode())) {
      const t = node as Text
      nodes.push(t)
      full += t.data
    }
    const idx = full.indexOf(quote)
    if (idx < 0) return false
    const start = idx
    const end = idx + quote.length
    const mark = document.createElement('mark')
    mark.className = `note-hl ${cls}`
    let acc = 0
    let placed = false
    for (const t of nodes) {
      const len = t.data.length
      const nodeStart = acc
      const nodeEnd = acc + len
      acc = nodeEnd
      if (end <= nodeStart || start >= nodeEnd) continue
      const cutStart = Math.max(start - nodeStart, 0)
      const cutEnd = Math.min(end - nodeStart, len)
      const before = cutStart > 0 ? document.createTextNode(t.data.slice(0, cutStart)) : null
      const hit = document.createTextNode(t.data.slice(cutStart, cutEnd))
      const after = cutEnd < len ? document.createTextNode(t.data.slice(cutEnd)) : null
      mark.appendChild(hit)
      const frag = document.createDocumentFragment()
      if (before) frag.appendChild(before)
      if (!placed) {
        frag.appendChild(mark)
        placed = true
      }
      if (after) frag.appendChild(after)
      t.replaceWith(frag)
    }
    return true
  }

  /** 按当前章节笔记重新渲染正文高亮（先展开旧 mark 再包裹，保持幂等）。 */
  function applyHighlights() {
    const el = scrollEl.value
    if (!el) return
    let leftover: Element | null = null
    while ((leftover = el.querySelector('.note-hl'))) {
      leftover.replaceWith(...Array.from(leftover.childNodes))
    }
    const chapterNotes = notes.value.filter((n) => n.chapter_id === currentChapterId.value)
    if (!chapterNotes.length) return
    const ordered = [...chapterNotes].sort((a, b) => b.quote_text.length - a.quote_text.length)
    el.querySelectorAll('.para').forEach((para) => {
      const box = para.querySelector('.md-render') as HTMLElement | null
      if (!box) return
      for (const n of ordered) {
        wrapQuoteInElement(box, n.quote_text, NOTE_HL_CLASS[n.note_type] ?? 'note-hl-highlight')
      }
    })
  }

  async function addNote(type: NoteType, quote: string, text: string) {
    if (!currentChapterId.value) return
    try {
      const note = await createNote(bookId.value, {
        chapter_id: currentChapterId.value,
        quote_text: quote,
        note_text: text,
        note_type: type,
      })
      notes.value.push(note)
      notes.value.sort((a, b) => (a.chapter_id ?? 0) - (b.chapter_id ?? 0))
      ElMessage.success(type === '不理解' ? '已标记为不理解' : '笔记已保存')
    } catch (err) {
      ElMessage.error((err as Error).message)
    }
  }

  function quickNote(paraIdx: number, type: NoteType) {
    const paraEl = scrollEl.value?.querySelector(`[data-para="${paraIdx}"] .md-render`)
    const quote = (paraEl?.textContent ?? blocks.value[paraIdx] ?? '').trim()
    if (type === '批注' || type === '思考') {
      noteDialog.value = { visible: true, type, quote, text: '', editingId: null }
      return
    }
    void addNote(type, quote, '')
  }

  async function addThinkList() {
    const sel = selection.takeSelection()
    if (!sel || !currentChapterId.value) return
    try {
      const note = await createNote(bookId.value, {
        chapter_id: currentChapterId.value,
        quote_text: sel,
        note_text: '',
        note_type: '思考',
      })
      notes.value.push(note)
      ElMessage.success('已加入思考清单')
    } catch (err) {
      ElMessage.error((err as Error).message)
    }
  }

  function selNote(type: NoteType) {
    const quote = selection.takeSelection()
    if (type === '批注' || type === '思考') {
      noteDialog.value = { visible: true, type, quote, text: '', editingId: null }
      return
    }
    void addNote(type, quote, '')
  }

  function noteChapter(n: NoteItem) {
    return chapters.value.find((c) => c.id === n.chapter_id)
  }

  async function jumpToNote(n: NoteItem) {
    notesDrawer.value = false
    if (n.chapter_id && n.chapter_id !== currentChapterId.value) {
      await loadChapter(n.chapter_id, false)
    }
    if (!n.quote_text) return
    await nextTick()
    const idx = blocks.value.findIndex((b) => b.includes(n.quote_text) || n.quote_text.includes(b.slice(0, 50)))
    if (idx >= 0 && scrollEl.value) {
      const para = scrollEl.value.querySelector(`[data-para="${idx}"]`) as HTMLElement | null
      para?.scrollIntoView({ block: 'start' })
    }
  }

  function editNote(n: NoteItem) {
    noteDialog.value = { visible: true, type: n.note_type, quote: n.quote_text, text: n.note_text, editingId: n.id }
  }

  async function removeNote(n: NoteItem) {
    try {
      await deleteNote(n.id)
      notes.value = notes.value.filter((x) => x.id !== n.id)
      ElMessage.success('已删除')
    } catch (err) {
      ElMessage.error((err as Error).message)
    }
  }

  async function saveNoteDialog() {
    const d = noteDialog.value
    if (d.editingId) {
      try {
        const updated = await updateNote(d.editingId, { note_text: d.text, note_type: d.type })
        const idx = notes.value.findIndex((n) => n.id === updated.id)
        if (idx >= 0) notes.value[idx] = updated
        ElMessage.success('已更新')
      } catch (err) {
        ElMessage.error((err as Error).message)
        return
      }
    } else {
      await addNote(d.type, d.quote, d.text)
    }
    noteDialog.value.visible = false
  }

  const typeTag = (t: NoteType) =>
    t === '不理解' ? 'danger' : t === '高亮' ? 'warning' : t === '思考' ? 'success' : 'primary'

  watch(notes, () => {
    void nextTick().then(applyHighlights)
  })

  function setNotes(list: NoteItem[]) {
    notes.value = list
  }

  return {
    notes, notesDrawer, noteDialog, setNotes, applyHighlights, addNote,
    quickNote, selNote, addThinkList, noteChapter, jumpToNote,
    editNote, removeNote, saveNoteDialog, typeTag,
  }
}
