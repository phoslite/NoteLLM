import { nextTick, ref, watch, type ComputedRef, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createNote, deleteNote, updateNote } from '@/api/reading'
import { findQuoteRange, normalizeHlText, paraTextsFingerprint, type HlTextNode, type HlRange } from '@/utils/highlight'
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

  /** 本次会话内「引用文本 → 选区所在段落下标」，用于归一化匹配失败时回退整段高亮。 */
  const quoteParaIdx = new Map<string, number>()

  /** 笔记 → 所在段落下标（增量高亮定位缓存；章节切换后按当前章笔记过滤使用）。 */
  const noteParaIdx = new Map<number, number>()
  /** 段落下标 → 该段需渲染的笔记 id 集合（上一轮 applyHighlights 结果，影响段判定用）。 */
  const paraNoteIds = new Map<number, Set<number>>()
  /** 当前章节段落归一化文本索引（textContent 级粗定位；key = 章节 id + 段落数 + 内容指纹）。 */
  let paraTextsCache: string[] | null = null
  let paraTextsKey = ''

  /** 收集容器内文本节点：跳过 .katex 公式与 .note-hl 内节点参与匹配（公式自动跳过、防嵌套 mark）。 */
  function collectHlNodes(root: HTMLElement): HlTextNode[] {
    const nodes: HlTextNode[] = []
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
    let node: Node | null
    while ((node = walker.nextNode())) {
      const t = node as Text
      const parent = t.parentElement
      if (!parent) continue
      const inKatex = parent.closest('.katex') != null
      const inMark = parent.closest('.note-hl') != null
      nodes.push({ node: t, text: t.data, matchable: !inKatex && !inMark, inMark })
    }
    return nodes
  }

  /** 把命中的区间切片包裹进同一个 <mark>（支持跨文本节点）。 */
  function wrapHits(nodes: HlTextNode[], hits: HlRange[], cls: string) {
    const mark = document.createElement('mark')
    mark.className = `note-hl ${cls}`
    let placed = false
    for (const h of hits) {
      const t = nodes[h.nodeIndex].node
      const before = h.start > 0 ? document.createTextNode(t.data.slice(0, h.start)) : null
      const hit = document.createTextNode(t.data.slice(h.start, h.end))
      const after = h.end < t.data.length ? document.createTextNode(t.data.slice(h.end)) : null
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
  }

  /** 整段回退：把段落内所有可匹配文本节点（跳过公式与已有 mark）包进一个 mark。 */
  function highlightWholeParagraph(el: HTMLElement, cls: string): boolean {
    const nodes = collectHlNodes(el).filter((n) => n.matchable)
    if (!nodes.length) return false
    const mark = document.createElement('mark')
    mark.className = `note-hl ${cls}`
    let placed = false
    for (const n of nodes) {
      const t = n.node
      const hit = document.createTextNode(t.data)
      mark.appendChild(hit)
      if (!placed) {
        const frag = document.createDocumentFragment()
        frag.appendChild(mark)
        t.replaceWith(frag)
        placed = true
      } else {
        t.remove()
      }
    }
    return true
  }

  /**
   * 在容器 DOM 中归一化匹配 quote 并包裹 <mark>。
   * - 匹配剥离 KaTeX 数学文本与换行（空白归一化）后执行；
   * - 命中已有 mark 内部（m4 防嵌套）视为成功但不包裹；
   * - 其余失败（公式段落 / 选区可见文本与 DOM 文本不一致）返回 false，调用方回退整段高亮。
   */
  function wrapQuoteInElement(el: HTMLElement, quote: string, cls: string): boolean {
    if (!quote) return false
    const nodes = collectHlNodes(el)
    const hits = findQuoteRange(nodes, quote)
    if (hits) {
      wrapHits(nodes, hits, cls)
      return true
    }
    // 归一化后仅存在于已有 mark 内部 → 跳过（防止二次包裹嵌套 mark）
    if (findQuoteRange(nodes.map((n) => ({ ...n, matchable: n.matchable || n.inMark })), quote)) return true
    return false
  }

  /** 解包指定段内全部旧 mark（幂等：无 mark 时无操作）。 */
  function unwrapPara(paraIdx: number) {
    const el = scrollEl.value
    if (!el) return
    const para = el.querySelector(`.para[data-para="${paraIdx}"]`) as HTMLElement | null
    if (!para) return
    let leftover: Element | null = null
    while ((leftover = para.querySelector('.note-hl'))) {
      leftover.replaceWith(...Array.from(leftover.childNodes))
    }
  }

  /** 当前章节段落归一化文本索引（textContent 级，含公式/旧 mark 文本——粗定位只要段级命中）。 */
  function buildParaTexts(chapterId: number): string[] {
    const el = scrollEl.value
    const paras = el?.querySelectorAll('.para') ?? []
    const texts: string[] = []
    for (const para of paras) {
      const box = para.querySelector('.md-render') as HTMLElement | null
      texts.push(normalizeHlText(box?.textContent ?? ''))
    }
    // P2-3：缓存键含内容指纹——同章同段数但内容变化（重渲染/重导入）时不得复用旧文本定位
    const key = `${chapterId}:${paras.length}:${paraTextsFingerprint(texts)}`
    if (paraTextsCache && paraTextsKey === key) return paraTextsCache
    paraTextsKey = key
    paraTextsCache = texts
    return paraTextsCache
  }

  /** 定位笔记所在段落：优先缓存；未缓存时按段落文本索引找第一个包含 quote 的段，
   *  失配再回退本会话选区记录（quoteParaIdx）。返回段落下标或 null。 */
  function locateNotePara(n: NoteItem, texts: string[]): number | null {
    const normQ = normalizeHlText(n.quote_text || '')
    const cached = noteParaIdx.get(n.id)
    // P2-4：信任缓存前校验内容（normQ 非空时）；跨章同段数/同章内容变化时失配即重定位并更新缓存
    if (cached != null && cached < texts.length && (!normQ || texts[cached].includes(normQ))) return cached
    let idx = -1
    if (normQ) idx = texts.findIndex((t) => t.includes(normQ))
    if (idx < 0) {
      const selIdx = quoteParaIdx.get(n.quote_text)
      if (selIdx != null && selIdx < texts.length) idx = selIdx
    }
    if (idx >= 0) noteParaIdx.set(n.id, idx)
    return idx >= 0 ? idx : null
  }

  /** 按当前章节笔记增量渲染正文高亮：只解包/重包受影响段落（上一轮关联段 ∪ 本轮定位段），
   *  段落文本索引只建一次，避免全章 O(P×N) 重扫；保持幂等与整段回退语义。 */
  function applyHighlights() {
    const el = scrollEl.value
    if (!el) return
    const chapterId = currentChapterId.value
    if (chapterId == null) return // 无章节上下文（切书瞬间）不渲染
    const chapterNotes = notes.value.filter((n) => n.chapter_id === chapterId)
    // 受影响段落 = 上一轮已关联段 ∪ 本轮定位段
    const affected = new Set<number>(paraNoteIds.keys())
    if (!chapterNotes.length) {
      for (const paraIdx of affected) unwrapPara(paraIdx)
      paraNoteIds.clear()
      return
    }
    const ordered = [...chapterNotes].sort((a, b) => b.quote_text.length - a.quote_text.length)
    const texts = buildParaTexts(chapterId)
    const nextParaNotes = new Map<number, Set<number>>()
    for (const n of ordered) {
      const paraIdx = locateNotePara(n, texts)
      if (paraIdx == null) continue
      affected.add(paraIdx)
      let ids = nextParaNotes.get(paraIdx)
      if (!ids) {
        ids = new Set()
        nextParaNotes.set(paraIdx, ids)
      }
      ids.add(n.id)
    }
    for (const paraIdx of affected) {
      unwrapPara(paraIdx)
      const ids = nextParaNotes.get(paraIdx)
      if (!ids) continue
      const para = el.querySelector(`.para[data-para="${paraIdx}"]`) as HTMLElement | null
      const box = para?.querySelector('.md-render') as HTMLElement | null
      if (!box) continue
      for (const n of ordered) {
        if (!ids.has(n.id)) continue
        const cls = NOTE_HL_CLASS[n.note_type] ?? 'note-hl-highlight'
        if (wrapQuoteInElement(box, n.quote_text, cls)) continue
        // E2E 四轮 #1：含公式段落精确匹配失败 → 回退「整段高亮」
        // （公式节点跳过、其余文本高亮，与手册「公式自动跳过、不影响其他高亮」一致）。
        // 仅回退到本次会话内记录过选区的段落，避免旧笔记误伤整段。
        if (quoteParaIdx.get(n.quote_text) === paraIdx) highlightWholeParagraph(box, cls)
      }
    }
    paraNoteIds.clear()
    for (const [paraIdx, ids] of nextParaNotes) paraNoteIds.set(paraIdx, new Set(ids))
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
    quoteParaIdx.set(quote, paraIdx)
    if (type === '批注' || type === '思考') {
      noteDialog.value = { visible: true, type, quote, text: '', editingId: null }
      return
    }
    void addNote(type, quote, '')
  }

  async function addThinkList() {
    const paraIdx = selection.selMenu.value.paraIdx
    const sel = selection.takeSelection()
    if (!sel || !currentChapterId.value) return
    if (paraIdx != null) quoteParaIdx.set(sel, paraIdx)
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
    const paraIdx = selection.selMenu.value.paraIdx
    const quote = selection.takeSelection()
    if (paraIdx != null) quoteParaIdx.set(quote, paraIdx)
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
      noteParaIdx.delete(n.id)
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
  }, { deep: true })  // F9 修复：push/sort/下标赋值均触发高亮刷新

  function setNotes(list: NoteItem[]) {
    notes.value = list
  }

  return {
    notes, notesDrawer, noteDialog, setNotes, applyHighlights, addNote,
    quickNote, selNote, addThinkList, noteChapter, jumpToNote,
    editNote, removeNote, saveNoteDialog, typeTag,
  }
}