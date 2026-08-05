<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getBook } from '@/api/books'
import { exportNotesPdfUrl, exportNotesUrl, getChapterContent, getProgress, listNotes, setAllChaptersRead, setChapterRead } from '@/api/reading'
import { useBookStore } from '@/stores/book'
import type { BookDetail, BookmarkItem, BookItem, ChapterItem } from '@/types'
import { cachedSplitBlocks } from '@/utils/content'
import MdRender from '@/components/MdRender.vue'
import MindMapPanel from '@/components/MindMapPanel.vue'
import ReaderLeftPanel from '@/components/ReaderLeftPanel.vue'
import ReaderChatPanel from '@/components/ReaderChatPanel.vue'
import BookmarkDrawer from '@/components/BookmarkDrawer.vue'
import PageDoodleCanvas from '@/components/PageDoodleCanvas.vue'
import DoodleToolbar from '@/components/DoodleToolbar.vue'
import { useReaderDoodle } from '@/composables/useReaderDoodle'
import { useReaderSelection } from '@/composables/useReaderSelection'
import { useReaderNotes } from '@/composables/useReaderNotes'
import { useReaderProgress } from '@/composables/useReaderProgress'
import { useReaderMindmap } from '@/composables/useReaderMindmap'
import { useReaderAi } from '@/composables/useReaderAi'
import { useReaderArchive } from '@/composables/useReaderArchive'
import { useReaderPageCache } from '@/composables/useReaderPageCache'

const route = useRoute()
const router = useRouter()
const store = useBookStore()

/* ---------- 阅读上下文 ---------- */
const book = ref<BookDetail | null>(null)
const currentChapterId = ref<number | null>(null)
const blocks = ref<string[]>([])
const pageMode = ref(false) // 扫描版 PDF：按原始页读图
const pageIndex = ref<number | null>(null)
const loadError = ref(false)
const chapterLoading = ref(false)
const hoverPara = ref<number | null>(null)
const scrollEl = ref<HTMLElement | null>(null)

const bookId = computed(() => Number(route.params.bookId))
const books = computed<BookItem[]>(() => {
  // 阅读页书架：只展示最近打开过的 5 本（当前书籍恒在列表内，避免刚打开尚未保存进度时消失）
  const recents = store.recentBooks()
  const cur = book.value
  if (!cur) return recents
  return [cur, ...recents.filter((b) => b.id !== cur.id)].slice(0, 5)
})
const chapters = computed(() => book.value?.chapters ?? [])
const currentChapter = computed(() => chapters.value.find((c) => c.id === currentChapterId.value))
const pageImageUrl = computed(() => (pageIndex.value != null ? `/api/books/${bookId.value}/pages/${pageIndex.value}` : ''))
// 扫描版页图缩放：'fit' = 适配宽度；number = 相对原图倍率（1 = 原始大小）
const pageZoom = ref<'fit' | number>('fit')
const pageNaturalWidth = ref(0)
const pageImgStyle = computed(() => {
  if (pageZoom.value === 'fit') return { maxWidth: '100%' }
  const w = Math.round(pageNaturalWidth.value * pageZoom.value)
  return w > 0 ? { width: `${w}px`, maxWidth: 'none' } : { maxWidth: '100%' }
})
const pageZoomText = computed(() => (pageZoom.value === 'fit' ? '自适应' : `${Math.round(pageZoom.value * 100)}%`))
function zoomBy(factor: number) {
  const base = pageZoom.value === 'fit' ? 1 : pageZoom.value
  pageZoom.value = Math.min(3, Math.max(0.5, Math.round(base * factor * 100) / 100))
  void nextTick(onPageImgResize)
}
function onPageImgLoad(e: Event) {
  pageNaturalWidth.value = (e.target as HTMLImageElement).naturalWidth || 0
  onPageImgResize()
}
const totalCount = computed(() => book.value?.chapters.length ?? 0)

/* ---------- PDF 页缓存（M7 多模态视觉提取） ---------- */
const pageCache = useReaderPageCache({ bookId, book, pageIndex })
const { pageCacheStatus, pageCacheBusy, refreshPageCacheStatus, reExtractCurrentPage, rebuildPageCache } = pageCache

/* ---------- 书签 ---------- */
const bookmarkDrawer = ref(false)

function jumpToBookmark(bm: BookmarkItem) {
  if (bm.page_index != null) {
    // PDF 整页书签：找到对应页章节并跳转
    const ch = chapters.value.find((c) => c.page_index === bm.page_index)
    if (ch) {
      void flushAndLoad(ch.id)
      return
    }
  }
  if (bm.chapter_id != null) {
    const ch = chapters.value.find((c) => c.id === bm.chapter_id)
    if (ch) {
      void flushAndLoad(ch.id).then(() => {
        if (bm.para_pos != null) scrollToPara(Number(bm.para_pos))
      })
    }
  }
}

/** 文本书书签跳转：滚动到指定段落。 */
function scrollToPara(para: number) {
  void nextTick(() => {
    const el = scrollEl.value
    if (!el) return
    const target = el.querySelector(`[data-para="${para}"]`) as HTMLElement | null
    if (target) {
      const top = target.offsetTop - el.offsetTop - 16
      el.scrollTop = Math.max(0, top)
    }
  })
}

/* ---------- 划词菜单 ---------- */
const selection = useReaderSelection(scrollEl)
const { selMenu, onMouseUp, onDocMouseDown, closeSelMenu, takeSelection } = selection

/* ---------- 阅读进度 ---------- */
const progress = useReaderProgress({
  bookId,
  scrollEl,
  currentChapterId,
  getCurrentChapter: () => currentChapter.value,
  onAutoRead: async () => {
    const detail = await getBook(bookId.value).catch(() => null)
    if (detail) book.value = detail
    store.fetchBooks()
  },
  refreshShelf: () => {
    if (store.books.length) store.fetchBooks()
  },
})
const { onScroll, saveNow, checkAutoRead, markChapterOpened, applyRestore, setCache, resetForBook, dispose } = progress

/* ---------- 笔记 ---------- */
const notesApi = useReaderNotes({
  bookId,
  scrollEl,
  currentChapterId,
  chapters,
  blocks,
  selection,
  loadChapter: flushAndLoad,
})
const { notes, notesDrawer, noteDialog, setNotes, applyHighlights, addNote, quickNote, selNote, addThinkList, noteChapter, jumpToNote, editNote, removeNote, saveNoteDialog, typeTag } = notesApi

/* ---------- 脑图 ---------- */
const mindmap = useReaderMindmap({
  bookId,
  currentChapterId,
  chapters,
  scrollEl,
  closeSelection: closeSelMenu,
  loadChapter,
})
const { mindmapOpen, mindmapLoading, mindmapError, mindmapData, openMindmap, jumpToMindmapPos } = mindmap

/** 把当前脑图大纲插入为本章批注（quote 使用占位标记，不会与正文误匹配）。 */
function insertMindmapAsNote() {
  if (!mindmapData.value?.markdown) return
  const label = mindmapData.value.title || '思维导图'
  void addNote('批注', `【思维导图：${label}】`, mindmapData.value.markdown)
}

/* ---------- AI 助手右侧折叠 ---------- */
function loadChatCollapsed(): boolean {
  try { return localStorage.getItem('reader.chatCollapsed') === '1' } catch { return false }
}
const chatCollapsed = ref(loadChatCollapsed())
const chatUnread = ref(0)
function toggleChatCollapsed() {
  chatCollapsed.value = !chatCollapsed.value
  try { localStorage.setItem('reader.chatCollapsed', chatCollapsed.value ? '1' : '0') } catch { /* 存储异常忽略 */ }
  if (!chatCollapsed.value) chatUnread.value = 0
}

/* ---------- AI 助手 ---------- */
const ai = useReaderAi({
  bookId,
  currentChapterId,
  currentChapter,
  scrollEl,
  takeSelection,
  openMindmap,
  scrollChat: () => chatPanel.value?.scrollToBottom(),
  onAssistantDone: () => { if (chatCollapsed.value) chatUnread.value += 1 },
})
const { chatMessages, chatMode, aiInput, streaming, streamError, currentChapterTitle, presetPrompt, switchMode, sendChat, abortChat, clearChat, copyChat, resetChat, askSelection } = ai

const chatPanel = ref<InstanceType<typeof ReaderChatPanel> | null>(null)

/* ---------- 页图涂鸦（PDF 按页阅读，依赖 AI 划线提问） ---------- */
const doodle = useReaderDoodle({
  bookId,
  pageIndex,
  onAskCrop: (question, crop) => {
    aiInput.value = question
    void sendChat(crop)
  },
})
const {
  doodleElements, doodleTool, doodleColor, doodleLineWidth, doodleCanvasRef,
  doodleCanUndo, doodleNoteDialog, pageDisplaySize,
  onPageImgResize, loadDoodle, scheduleDoodleSave, onDoodleEditNote,
  saveDoodleNote, askCropOnDoodle, switchPage: switchDoodlePage, dispose: disposeDoodle,
} = doodle

/* ---------- 章节加载 ---------- */
async function loadChapter(chapterId: number, restore: boolean) {
  if (!book.value) return
  chapterLoading.value = true
  try {
    const content = await getChapterContent(bookId.value, chapterId)
    currentChapterId.value = chapterId
    markChapterOpened()
    const prevPageMode = pageMode.value
    const prevPage = pageIndex.value
    pageMode.value = content.page_index != null
    pageIndex.value = content.page_index
    await switchDoodlePage(prevPageMode, prevPage, content.page_index)
    blocks.value = pageMode.value ? [] : cachedSplitBlocks(content.content_text)
    await nextTick()
    if (!pageMode.value) applyHighlights()
    applyRestore(chapterId, restore)
    if (currentChapterId.value && !currentChapter.value?.read_flag) {
      await saveNow()
    }
  } catch {
    loadError.value = true
  } finally {
    chapterLoading.value = false
  }
}

async function loadAll() {
  loadError.value = false
  try {
    const [detail, savedProgress, noteList] = await Promise.all([
      getBook(bookId.value),
      getProgress(bookId.value).catch(() => null),
      listNotes(bookId.value).catch(() => []),
    ])
    book.value = detail
    setNotes(noteList)
    setCache(savedProgress)
    void refreshPageCacheStatus()
    const target = savedProgress?.chapter_id && detail.chapters.some((c) => c.id === savedProgress.chapter_id)
      ? savedProgress.chapter_id
      : (detail.chapters[0]?.id ?? null)
    await loadChapter(target!, true)
  } catch {
    book.value = null
    loadError.value = true
  }
}

async function flushAndLoad(chapterId: number) {
  await saveNow()
  await loadChapter(chapterId, false)
}

/* ---------- 交互 ---------- */
function goBook(id: number) {
  if (id !== bookId.value) router.push({ name: 'reader', params: { bookId: id } })
}

function onChapterClick(chapterId: number) {
  if (chapterId === currentChapterId.value) return
  void flushAndLoad(chapterId)
}


async function toggleChapterRead(c: ChapterItem) {
  const target = !c.read_flag
  try {
    await setChapterRead(bookId.value, c.id, target)
    const detail = await getBook(bookId.value).catch(() => null)
    if (detail) book.value = detail
    store.fetchBooks()
    ElMessage.success(target ? `已标记第${c.index}章已读` : `已取消第${c.index}章已读`)
  } catch (err) {
    ElMessage.error((err as Error).message)
  }
}

async function toggleFinished() {
  if (!book.value) return
  const finished = book.value.status === '读完'
  if (finished) {
    try {
      await ElMessageBox.confirm('将整本书标记为「在读」并清除全部章节/页面的已读标记？', '提示', { type: 'warning' })
    } catch {
      return
    }
  }
  try {
    await setAllChaptersRead(bookId.value, !finished)
    const detail = await getBook(bookId.value).catch(() => null)
    if (detail) book.value = detail
    store.fetchBooks()
    ElMessage.success(finished ? '已标记为在读' : '已标记读完')
  } catch (err) {
    ElMessage.error((err as Error).message)
  }
}

const { archiving, archiveAndSummarize } = useReaderArchive({
  bookId,
  book,
  onDone: async () => {
    const detail = await getBook(bookId.value).catch(() => null)
    if (detail) book.value = detail
    store.fetchBooks()
  },
})

watch(bookId, () => {
  resetForBook()
  resetChat()
  void loadAll()
}, { immediate: true })

let readCheckTimer: ReturnType<typeof setInterval> | null = null

function startReadCheck() {
  if (readCheckTimer) return
  readCheckTimer = setInterval(() => void checkAutoRead(), 1000)
}

function stopReadCheck() {
  if (readCheckTimer) {
    clearInterval(readCheckTimer)
    readCheckTimer = null
  }
}

/** 页面隐藏/最小化时暂停自动读完检查：隐藏时长不计入阅读，且避免后台无用轮询。 */
function onVisibilityChange() {
  if (document.visibilityState === 'visible') {
    startReadCheck()
    void checkAutoRead()
  } else {
    stopReadCheck()
  }
}

onMounted(() => {
  if (!store.books.length) store.fetchBooks()
  document.addEventListener('mouseup', onMouseUp)
  document.addEventListener('mousedown', onDocMouseDown)
  document.addEventListener('visibilitychange', onVisibilityChange)
  startReadCheck()
})

onBeforeUnmount(() => {
  document.removeEventListener('mouseup', onMouseUp)
  document.removeEventListener('mousedown', onDocMouseDown)
  document.removeEventListener('visibilitychange', onVisibilityChange)
  stopReadCheck()
  dispose()
  disposeDoodle()
})
</script>

<template>
  <div class="reader">
    <ReaderLeftPanel
      :books="books"
      :book="book"
      :book-id="bookId"
      :current-chapter-id="currentChapterId"
      :load-error="loadError"
      @select-book="goBook"
      @select-chapter="onChapterClick"
      @toggle-read="toggleChapterRead"
    />

    <main class="reading-panel">
      <div class="reading-toolbar">
        <div class="toolbar-row">
          <div class="toolbar-left">
            <template v-if="pageMode">
              <span class="page-indicator">第 {{ currentChapter?.index ?? pageIndex ?? '-' }}/{{ totalCount }} 页</span>
              <span class="page-zoombar">
                <button type="button" class="mini-btn" title="适配宽度" :class="{ active: pageZoom === 'fit' }" @click="pageZoom = 'fit'">适配</button>
                <button type="button" class="mini-btn" title="原始大小（1:1）" :class="{ active: pageZoom === 1 }" @click="pageZoom = 1">1:1</button>
                <button type="button" class="mini-btn" :disabled="pageZoom !== 'fit' && pageZoom >= 3" @click="zoomBy(1.25)">＋</button>
                <button type="button" class="mini-btn" :disabled="pageZoom !== 'fit' && pageZoom <= 0.5" @click="zoomBy(0.8)">－</button>
                <span v-if="pageZoom !== 'fit'" class="page-zoom-text">{{ pageZoomText }}</span>
              </span>
            </template>
            <h2 v-else-if="currentChapter" class="chapter-heading">
              <MdRender :source="currentChapter.title" inline />
            </h2>
            <h2 v-else class="chapter-heading">选择章节开始阅读</h2>
          </div>
          <div class="toolbar-actions">
            <el-button
              v-if="pageMode && currentChapter"
              class="read-status-btn"
              size="small"
              :type="currentChapter.read_flag ? 'success' : 'primary'"
              :plain="!currentChapter.read_flag"
              @click="toggleChapterRead(currentChapter)"
            >
              {{ currentChapter.read_flag ? '✓ 已读' : '标记已读' }}
            </el-button>
            <el-button size="small" @click="bookmarkDrawer = true">书签</el-button>
            <el-badge :value="notes.length" :hidden="!notes.length" type="primary">
              <el-button size="small" @click="notesDrawer = true">笔记</el-button>
            </el-badge>
            <el-button
              size="small"
              :type="book?.status === '读完' ? 'warning' : 'success'"
              plain
              @click="toggleFinished"
            >
              {{ book?.status === '读完' ? '标记在读' : '标记读完' }}
            </el-button>
            <el-button size="small" type="primary" plain :loading="archiving" @click="archiveAndSummarize">
              归档
            </el-button>
          </div>
        </div>
        <div v-if="pageMode" class="toolbar-tools">
          <DoodleToolbar
            class="doodle-row"
            v-model="doodleTool"
            :can-undo="doodleCanUndo"
            @undo="doodleCanvasRef?.undo()"
            @clear="doodleElements = []"
            @update:color="doodleColor = $event"
            @update:line-width="doodleLineWidth = $event"
          />
          <span class="tool-tools-right">
            <span v-if="pageCacheStatus" class="page-cache-status" title="已提取缓存页数 / 总页数">
              页缓存 {{ pageCacheStatus.cached }}/{{ pageCacheStatus.total }}
            </span>
            <el-button size="small" title="重新提取当前页缓存" :loading="pageCacheBusy" @click="reExtractCurrentPage">重提</el-button>
            <el-button size="small" title="重建全部页缓存" :loading="pageCacheBusy" @click="rebuildPageCache">重建</el-button>
          </span>
        </div>
      </div>
      <div ref="scrollEl" class="reading-scroll" @scroll="onScroll">
        <div v-if="chapterLoading" class="loading-tip">章节加载中…</div>
        <div v-else-if="pageMode" class="page-view">
          <div class="page-scroll">
            <PageDoodleCanvas
              :width="pageDisplaySize.w"
              :height="pageDisplaySize.h"
              v-model="doodleElements"
              :tool="doodleTool"
              :color="doodleColor"
              :line-width="doodleLineWidth"
              :active="true"
              ref="doodleCanvasRef"
              @ask-crop="askCropOnDoodle"
              @edit-note="onDoodleEditNote"
              @can-undo="doodleCanUndo = $event"
            >
              <template #image>
                <img
                  :src="pageImageUrl"
                  class="page-img"
                  alt="PDF 原始页"
                  :style="pageImgStyle"
                  @load="onPageImgLoad"
                />
              </template>
            </PageDoodleCanvas>
          </div>
        </div>
        <div v-if="pageMode" class="page-preload" aria-hidden="true">
          <img v-if="pageIndex && pageIndex > 1" :src="`/api/books/${bookId}/pages/${pageIndex - 1}`" alt="" loading="eager" decoding="async" />
          <img v-if="pageIndex && pageIndex < totalCount" :src="`/api/books/${bookId}/pages/${pageIndex + 1}`" alt="" loading="eager" decoding="async" />
        </div>
        <template v-else>
          <div
            v-for="(block, i) in blocks"
            :key="i"
            class="para"
            :data-para="i"
            @mouseenter="hoverPara = i"
            @mouseleave="hoverPara = null"
          >
            <MdRender :source="block" />
            <div v-show="hoverPara === i" class="para-actions">
              <button type="button" class="mini-btn danger" @click="quickNote(i, '不理解')">❓ 不理解</button>
              <button type="button" class="mini-btn" @click="quickNote(i, '高亮')">✍ 高亮</button>
              <button type="button" class="mini-btn" @click="quickNote(i, '批注')">批注</button>
              <button type="button" class="mini-btn" @click="quickNote(i, '思考')">思考</button>
            </div>
          </div>
          <div v-if="!blocks.length && !chapterLoading" class="empty-tip">从左侧目录选择章节开始阅读</div>
        </template>
      </div>

      <div
        v-if="selMenu.visible"
        class="sel-menu"
        :style="{ top: selMenu.top + 'px', left: selMenu.left + 'px' }"
        @mousedown.stop
      >
        <button type="button" class="mini-btn" @click="selNote('高亮')">✍ 高亮</button>
        <button type="button" class="mini-btn" @click="selNote('批注')">批注</button>
        <button type="button" class="mini-btn" @click="selNote('思考')">思考</button>
        <button type="button" class="mini-btn danger" @click="selNote('不理解')">❓ 不理解</button>
        <button type="button" class="mini-btn ai" @click="askSelection">🤖 解释选中段</button>
        <button type="button" class="mini-btn ai" @click="openMindmap(selMenu.text)">🧠 该段脑图</button>
        <button type="button" class="mini-btn ai" @click="addThinkList">📌 加入思考清单</button>
      </div>
    </main>

    <ReaderChatPanel
      ref="chatPanel"
      v-model:input="aiInput"
      :messages="chatMessages"
      :streaming="streaming"
      :stream-error="streamError"
      :context-title="currentChapterTitle"
      :chat-mode="chatMode"
      :collapsed="chatCollapsed"
      :unread="chatUnread"
      @mode-change="switchMode"
      @preset="presetPrompt"
      @send="sendChat"
      @abort="abortChat"
      @clear="clearChat"
      @copy="copyChat"
      @toggle-collapse="toggleChatCollapsed"
    />

    <el-drawer v-model="notesDrawer" title="本书笔记" size="420px">
      <div class="drawer-actions">
        <a class="export-link" :href="exportNotesUrl(bookId)" download>⬇ 导出 Markdown</a>
        <a class="export-link" :href="exportNotesPdfUrl(bookId)" download>⬇ 导出 PDF</a>
      </div>
      <el-empty v-if="!notes.length" description="暂无笔记" />
      <div v-for="n in notes" :key="n.id" class="note-item">
        <div class="note-head">
          <el-tag size="small" :type="typeTag(n.note_type) as any">{{ n.note_type }}</el-tag>
          <MdRender v-if="noteChapter(n)" class="note-loc" :source="`第${noteChapter(n)!.index}章 ${noteChapter(n)!.title}`" inline />
          <span v-else class="note-loc">未定位</span>
          <span class="note-actions">
            <el-button size="small" text @click="jumpToNote(n)">定位</el-button>
            <el-button size="small" text @click="editNote(n)">编辑</el-button>
            <el-button size="small" text type="danger" @click="removeNote(n)">删除</el-button>
          </span>
        </div>
        <blockquote v-if="n.quote_text" class="note-quote">{{ n.quote_text }}</blockquote>
        <div v-if="n.note_text" class="note-text"><MdRender :source="n.note_text" /></div>
      </div>
    </el-drawer>

    <BookmarkDrawer
      v-model="bookmarkDrawer"
      :book-id="bookId"
      :chapters="chapters"
      :current-chapter-id="currentChapterId"
      :current-page-index="pageIndex"
      @jump="jumpToBookmark"
    />

    <el-dialog v-model="doodleNoteDialog.visible" title="划线批注" width="480px">
      <div class="dialog-field">
        <div class="field-label">批注内容（支持 Markdown / LaTeX）</div>
        <el-input v-model="doodleNoteDialog.text" type="textarea" :rows="5" placeholder="写点什么…" />
      </div>
      <template #footer>
        <el-button @click="doodleNoteDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="saveDoodleNote">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="noteDialog.visible" :title="noteDialog.editingId ? '编辑笔记' : `添加${noteDialog.type}笔记`" width="480px">
      <div class="dialog-field" v-if="noteDialog.quote">
        <div class="field-label">原文</div>
        <blockquote class="note-quote">{{ noteDialog.quote }}</blockquote>
      </div>
      <div class="dialog-field">
        <div class="field-label">笔记内容（支持 Markdown / LaTeX）</div>
        <el-input v-model="noteDialog.text" type="textarea" :rows="5" placeholder="写点什么…" />
      </div>
      <template #footer>
        <el-button @click="noteDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="saveNoteDialog">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="mindmapOpen" title="思维导图" width="780px" top="6vh" destroy-on-close>
      <MindMapPanel
        :tree="mindmapData?.tree ?? null"
        :title="mindmapData?.title ?? ''"
        :loading="mindmapLoading"
        :error="mindmapError"
        :markdown="mindmapData?.markdown ?? ''"
        :cached="mindmapData?.cached ?? false"
        @jump="jumpToMindmapPos"
        @insert-note="insertMindmapAsNote"
      />
    </el-dialog>
  </div>
</template>

<style scoped>
.reader { display: flex; height: 100%; position: relative; }

.reading-panel {
  box-sizing: border-box;
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--reading-bg);
}
.page-indicator {
  font-size: 13px;
  color: var(--text-secondary);
  white-space: nowrap;
}

.reading-toolbar {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 6px 16px;
  border-bottom: 1px solid var(--border-color);
}
.toolbar-row { display: flex; align-items: center; gap: 8px 12px; flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; }
.toolbar-row::-webkit-scrollbar { display: none; }
.toolbar-left { display: flex; align-items: center; gap: 8px; flex-wrap: nowrap; flex-shrink: 0; min-width: 0; }
.toolbar-actions { display: flex; align-items: center; gap: 4px; margin-left: auto; flex-shrink: 0; }
.toolbar-actions .el-button { padding: 5px 8px; }
.toolbar-tools { display: flex; align-items: center; gap: 6px; min-width: 0; }
.doodle-row { flex: 1; min-width: 0; }
.toolbar-tools .el-button { height: 22px; padding: 2px 8px; }
.tool-tools-right { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.chapter-heading {
  margin: 0; font-size: 16px; line-height: 1.5;
  min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.chapter-heading :deep(p), .chapter-heading :deep(span) { margin: 0; display: inline; }

.reading-scroll { flex: 1; overflow-y: auto; padding: 18px 40px 48px; }
.page-view { display: flex; flex-direction: column; align-items: center; gap: 8px; }
.page-zoombar { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.page-zoom-text { font-size: 12px; color: var(--text-secondary); min-width: 34px; text-align: center; }
.page-scroll { width: 100%; display: flex; justify-content: safe center; }
.page-img { max-width: 100%; box-shadow: 0 2px 12px rgba(0, 0, 0, 0.12); border-radius: 4px; }
.mini-btn.active { border-color: var(--primary-color); color: var(--primary-color); background: rgba(64, 158, 255, 0.08); }
.reading-scroll :deep(.note-hl) { border-radius: 3px; padding: 0 1px; }
.reading-scroll :deep(.note-hl-highlight) { background: rgba(250, 204, 21, 0.4); }
.reading-scroll :deep(.note-hl-confuse) { background: rgba(245, 108, 108, 0.3); text-decoration: underline wavy #f56c6c; }
.reading-scroll :deep(.note-hl-comment) { background: rgba(103, 194, 58, 0.22); border-bottom: 2px solid #67c23a; }
.reading-scroll :deep(.note-hl-think) { background: rgba(64, 158, 255, 0.22); border-bottom: 2px solid #409eff; }
.para { position: relative; padding: 2px 4px; border-radius: 6px; }
.para:hover { background: rgba(47, 111, 237, 0.04); }
.para-actions { position: absolute; right: 0; top: 0; display: flex; gap: 4px; z-index: 5; }
.mini-btn {
  border: 1px solid var(--border-color);
  background: #fff;
  color: var(--text-color);
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
  cursor: pointer;
  white-space: nowrap;
}
.mini-btn:hover { border-color: var(--primary-color); color: var(--primary-color); }
.mini-btn.danger:hover { border-color: #f56c6c; color: #f56c6c; }

.sel-menu {
  position: fixed;
  z-index: 100;
  display: flex;
  gap: 4px;
  padding: 6px;
  background: #fff;
  border: 1px solid var(--border-color);
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
}
.sel-menu .mini-btn.ai { color: var(--primary-color); }
.sel-menu .mini-btn.ai:hover { background: var(--panel-bg); }
.loading-tip { color: var(--text-secondary); font-size: 13px; padding: 20px 0; }
.page-preload img { position: absolute; left: -9999px; top: 0; width: 1px; height: 1px; opacity: 0.01; }
.empty-tip { color: var(--text-secondary); font-size: 12px; padding: 6px 2px; }

.drawer-actions { margin-bottom: 12px; display: flex; gap: 16px; }
.export-link { font-size: 13px; color: var(--primary-color); text-decoration: none; }
.note-item { border: 1px solid var(--border-color); border-radius: 8px; padding: 10px 12px; margin-bottom: 10px; }
.note-head { display: flex; align-items: center; gap: 8px; }
.note-loc { flex: 1; font-size: 12px; color: var(--text-secondary); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.note-actions { flex: none; }
.note-quote { margin: 8px 0; padding: 6px 10px; border-left: 3px solid var(--border-color); background: var(--panel-bg); font-size: 12px; color: var(--text-secondary); white-space: pre-wrap; word-break: break-word; }
.note-text { font-size: 13px; word-break: break-word; }
.note-text :deep(p) { margin: 0.3em 0; }
.dialog-field { margin-bottom: 12px; }
.field-label { font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; }
.page-cache-status { font-size: 12px; color: var(--text-secondary); margin-right: 4px; }
</style>
