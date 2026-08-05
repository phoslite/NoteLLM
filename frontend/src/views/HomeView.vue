<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRouter } from 'vue-router'
import { deleteBook, reorderBooks, searchBooks, updateBook, uploadBook } from '@/api/books'
import { useBookStore } from '@/stores/book'
import type { BookItem, SearchHit } from '@/types'
import { chapterPercent } from '@/utils/progress'
import { notifyTaskSubmitted } from '@/utils/task'
import GlobalChatPanel from '@/components/GlobalChatPanel.vue'
import { useGlobalAi } from '@/composables/useGlobalAi'

const store = useBookStore()
const router = useRouter()

const uploadRef = ref<HTMLInputElement | null>(null)
const searchQuery = ref('')
const activeTag = ref('')
const dragBook = ref<BookItem | null>(null)
const dragOverId = ref<number | null>(null)

/** 书架统计（总数 / 读完 / 在读），用于工具条展示 */
const shelfStats = computed(() => {
  const all = store.books
  return {
    total: all.length,
    done: all.filter((b) => b.status === '读完').length,
    reading: all.filter((b) => b.status === '在读').length,
  }
})

const statusMeta: Record<string, { label: string; cls: string }> = {
  读完: { label: '读完', cls: 'done' },
  在读: { label: '在读', cls: 'reading' },
  未读: { label: '未读', cls: 'todo' },
}

// 标签编辑：按书籍 id 独立控制弹层可见性（共享布尔值会导致一次点击弹出全部弹层）
const tagEditId = ref<number | null>(null)
const tagEditBook = ref<BookItem | null>(null)
const tagDraft = ref<string[]>([])

onMounted(() => store.fetchBooks())

/* ---------- 决策 37：主页全局 AI 对话（阅读之外，Skill/RAG 资产辅助） ---------- */
const globalAi = useGlobalAi()
const aiPanelCollapsed = ref(true)
const aiUnread = ref(0)
const aiInput = globalAi.input
function toggleAiPanel() {
  aiPanelCollapsed.value = !aiPanelCollapsed.value
  if (!aiPanelCollapsed.value) {
    aiUnread.value = 0
    void globalAi.refreshHistory() // 展开时载入该会话全部历史（需求 v1.73）
  }
}
/** 删除当前全局 AI 会话（二次确认；删除后换新会话键，重开为全新对话）。 */
async function onDeleteAiSession() {
  try {
    await ElMessageBox.confirm('确定删除当前会话？其全部对话历史与知识挑选缓存将一并移除，重开后为全新会话。', '删除会话', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await globalAi.deleteSession()
  ElMessage.success('已删除会话')
}

/** 折叠期间统计新增 AI 回复数（assistant 非流式消息）。 */
watch(globalAi.messages, (msgs) => {
  if (aiPanelCollapsed.value) {
    aiUnread.value = msgs.filter((m) => m.role === 'assistant' && !m.local).length
  }
})

/** 全部书籍的 tag 去重集合（用于筛选与补全候选） */
const allTags = computed(() => {
  const set = new Set<string>()
  for (const b of store.books) for (const t of b.tags) set.add(t)
  return [...set].sort()
})

/** 搜索（书名/作者/标签）+ 标签筛选后的书架 */
const displayedBooks = computed(() => {
  const kw = searchQuery.value.trim().toLowerCase()
  return store.books.filter((b) => {
    if (activeTag.value && !b.tags.includes(activeTag.value)) return false
    if (!kw) return true
    return [b.title, b.author ?? '', ...b.tags].some((t) => t.toLowerCase().includes(kw))
  })
})

/* ---------- 全书内容搜索（审查 A-5：FTS5 后端搜索入口，防抖 300ms） ---------- */
const searchHits = ref<SearchHit[]>([])
const showSearchHits = ref(false)
let searchTimer: number | undefined

watch(searchQuery, (kw) => {
  window.clearTimeout(searchTimer)
  const q = kw.trim()
  if (!q) {
    searchHits.value = []
    showSearchHits.value = false
    return
  }
  searchTimer = window.setTimeout(async () => {
    try {
      searchHits.value = await searchBooks(q)
      showSearchHits.value = true
    } catch {
      searchHits.value = []
      showSearchHits.value = false
    }
  }, 300)
})

function onSearchBlur() {
  // 延迟关闭，保证结果项 mousedown 先触发跳转
  setTimeout(() => {
    showSearchHits.value = false
  }, 150)
}

function goSearchHit(hit: SearchHit) {
  showSearchHits.value = false
  router.push(`/reader/${hit.book_id}`)
}

async function onFilePicked(e: Event) {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  try {
    const res = await uploadBook(file)
    ElMessage.success(`已导入《${res.title}》，后台处理中…`)
    notifyTaskSubmitted()
    await store.fetchBooks()
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    input.value = ''
  }
}

function openBook(book: BookItem) {
  router.push(`/reader/${book.id}`)
}

async function onDeleteBook(book: BookItem) {
  try {
    await ElMessageBox.confirm(`确定删除《${book.title}》？其笔记、对话记录与本地文件将一并移除。`, '删除书籍', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await deleteBook(book.id)
    ElMessage.success(`已删除《${book.title}》`)
    await store.fetchBooks()
  } catch (err) {
    ElMessage.error((err as Error).message)
  }
}

function latestText(b: BookItem) {
  return b.latest_chapter ? `最新章节：第${b.latest_chapter.index}章 ${b.latest_chapter.title}` : '最新章节：暂无'
}

// ---------- 拖拽换位 ----------
function onDragStart(book: BookItem, e: DragEvent) {
  dragBook.value = book
  dragOverId.value = null
  if (e.dataTransfer) e.dataTransfer.effectAllowed = 'move'
}

function onDragEnd() {
  dragBook.value = null
  dragOverId.value = null
}

/** dragleave 仅在真正离开卡片时清除高亮（避免移动到卡片子元素时误清除） */
function onDragLeave(e: DragEvent, id: number) {
  const rel = e.relatedTarget as Node | null
  if (!rel || !(e.currentTarget as Node).contains(rel)) {
    dragOverId.value = null
  }
}

async function onDrop(target: BookItem) {
  dragOverId.value = null
  const src = dragBook.value
  dragBook.value = null
  if (!src || src.id === target.id) return
  const arr = [...store.books]
  const si = arr.findIndex((b) => b.id === src.id)
  const ti = arr.findIndex((b) => b.id === target.id)
  if (si < 0 || ti < 0) return
  ;[arr[si], arr[ti]] = [arr[ti], arr[si]]
  store.books = arr
  try {
    await reorderBooks(arr.map((b) => b.id))
  } catch (err) {
    ElMessage.error((err as Error).message)
    await store.fetchBooks()
  }
}

// ---------- 标签编辑 ----------
function prepareTagEdit(book: BookItem) {
  tagEditBook.value = book
  tagDraft.value = [...book.tags]
}

function toggleTagEdit(book: BookItem) {
  tagEditId.value = tagEditId.value === book.id ? null : book.id
  prepareTagEdit(book)
}

async function onSaveTags() {
  const book = tagEditBook.value
  if (!book) return
  tagEditId.value = null
  try {
    const updated = await updateBook(book.id, { tags: tagDraft.value })
    const idx = store.books.findIndex((b) => b.id === book.id)
    if (idx >= 0) store.books[idx] = updated
    ElMessage.success('标签已更新')
  } catch (err) {
    ElMessage.error((err as Error).message)
  }
  tagEditBook.value = null
}

function toggleTagFilter(tag: string) {
  activeTag.value = activeTag.value === tag ? '' : tag
}
</script>

<template>
  <div class="home">
    <aside class="recent-panel">
      <div class="panel-head">
        <h2>近期阅读</h2>
        <span class="panel-count" v-if="store.recentBooks().length">{{ store.recentBooks().length }} 本</span>
      </div>
      <div v-if="store.recentBooks().length === 0" class="empty-block">
        <div class="empty-icon">📖</div>
        <div>暂无阅读记录</div>
        <div class="empty-sub">打开一本书开始阅读吧</div>
      </div>
      <div v-for="b in store.recentBooks()" :key="b.id" class="recent-item" @click="openBook(b)">
        <div class="recent-cover">
          <img v-if="b.cover_url" :src="b.cover_url" :alt="b.title" loading="lazy" decoding="async" />
          <span v-else>{{ b.title.charAt(0).toUpperCase() }}</span>
        </div>
        <div class="recent-body">
          <div class="recent-title" :title="b.title">{{ b.title }}</div>
          <div class="recent-line">已阅读 {{ b.read_chapters ?? 0 }}/{{ b.chapter_count }} 章</div>
          <el-progress :percentage="chapterPercent(b.read_chapters, b.chapter_count)" :stroke-width="5" :show-text="false" class="recent-progress" />
        </div>
      </div>
    </aside>

    <section class="shelf-panel">
      <div class="shelf-toolbar">
        <div class="toolbar-left">
          <div class="shelf-title">
            <h2>书架</h2>
            <span class="stats-chip" v-if="store.books.length">
              共 {{ shelfStats.total }} 本
              <i class="dot done"></i>{{ shelfStats.done }} 读完
              <i class="dot reading"></i>{{ shelfStats.reading }} 在读
            </span>
          </div>
          <div class="search-wrap">
            <el-input
              v-model="searchQuery"
              placeholder="搜索书名 / 作者 / 标签 / 全文"
              clearable
              class="search-input"
              @blur="onSearchBlur"
            >
              <template #prefix><span class="search-icon">🔍</span></template>
            </el-input>
            <div v-if="showSearchHits" class="search-hits">
              <template v-if="searchHits.length">
                <div
                  v-for="h in searchHits"
                  :key="h.chapter_id"
                  class="search-hit"
                  @mousedown.prevent="goSearchHit(h)"
                >
                  <div class="hit-title">
                    {{ h.title }}
                    <span class="hit-chapter">第 {{ h.chapter_index ?? '?' }} 章 · {{ h.chapter_title }}</span>
                  </div>
                  <div class="hit-snippet">{{ h.snippet }}</div>
                </div>
              </template>
              <div v-else class="search-hits-empty">未找到章节命中</div>
            </div>
          </div>
          <el-select
            v-model="activeTag"
            clearable
            filterable
            placeholder="按标签筛选"
            class="tag-filter"
          >
            <el-option v-for="t in allTags" :key="t" :label="t" :value="t" />
          </el-select>
        </div>
        <div class="toolbar-right">
          <span v-if="store.books.length" class="drag-hint">💡 拖动封面可交换位置</span>
          <el-button type="primary" round @click="uploadRef?.click()">＋ 导入书籍</el-button>
          <input ref="uploadRef" type="file" accept=".pdf,.md,.markdown,.txt,.epub" hidden @change="onFilePicked" />
        </div>
      </div>

      <div v-if="store.loading" class="empty-block">
        <div class="empty-icon">⏳</div>
        <div>加载中…</div>
      </div>
      <div v-else-if="store.books.length === 0" class="empty-block">
        <div class="empty-icon">📚</div>
        <div>书架还是空的</div>
        <div class="empty-sub">点击右上角「导入书籍」开始</div>
      </div>
      <div v-else-if="displayedBooks.length === 0" class="empty-block">
        <div class="empty-icon">🔍</div>
        <div>没有匹配的书籍</div>
        <div class="empty-sub">试试其他关键词或清除标签筛选</div>
      </div>
      <div v-else class="shelf-grid">
        <div
          v-for="b in displayedBooks"
          :key="b.id"
          class="book-card"
          :class="{ 'is-dragging': dragBook?.id === b.id, 'is-drag-over': dragOverId === b.id }"
          draggable="true"
          @dragstart="onDragStart(b, $event)"
          @dragend="onDragEnd"
          @dragover.prevent="dragOverId = b.id"
          @dragleave="onDragLeave($event, b.id)"
          @drop.prevent="onDrop(b)"
        >
          <span class="status-badge" :class="statusMeta[b.status]?.cls || 'todo'">
            {{ statusMeta[b.status]?.label || b.status || '未读' }}
          </span>
          <div class="book-actions">
            <el-popover
              :visible="tagEditId === b.id"
              placement="top"
              width="240"
              trigger="manual"
            >
              <template #reference>
                <button type="button" class="book-action-btn" title="编辑标签" @click.stop="toggleTagEdit(b)">🏷</button>
              </template>
              <div class="tag-editor">
                <el-select
                  v-model="tagDraft"
                  multiple
                  filterable
                  allow-create
                  default-first-option
                  :reserve-keyword="false"
                  :teleported="false"
                  placeholder="输入标签后回车"
                  style="width: 100%"
                >
                  <el-option v-for="t in allTags" :key="t" :label="t" :value="t" />
                </el-select>
                <div class="tag-select-spacer"></div>
                <div class="tag-editor-actions">
                  <el-button size="small" @click="tagEditId = null">取消</el-button>
                  <el-button size="small" type="primary" @click="onSaveTags">保存</el-button>
                </div>
              </div>
            </el-popover>
            <button type="button" class="book-action-btn danger" title="删除书籍" @click.stop="onDeleteBook(b)">🗑</button>
          </div>

          <div class="book-cover" @click="openBook(b)">
            <img v-if="b.cover_url" :src="b.cover_url" :alt="b.title" class="cover-img" loading="lazy" decoding="async" />
            <div v-else class="cover-placeholder">
              <span class="cover-letter">{{ b.title.charAt(0).toUpperCase() }}</span>
              <span class="cover-fmt">{{ b.format.toUpperCase() }}</span>
            </div>
          </div>
          <div class="book-title" :title="b.title" @click="openBook(b)">{{ b.title }}</div>

          <div class="book-tags">
            <span
              v-for="t in b.tags"
              :key="t"
              class="tag-chip"
              :class="{ active: activeTag === t }"
              :title="t"
              @click.stop="toggleTagFilter(t)"
            >{{ t }}</span>
            <span v-if="!b.tags.length" class="tag-empty">无标签</span>
          </div>

          <div class="book-read-info">
            <div class="read-chapters">已阅读 {{ b.read_chapters ?? 0 }}/{{ b.chapter_count }} 章</div>
            <div class="latest-chapter">{{ latestText(b) }}</div>
          </div>
          <el-progress :percentage="chapterPercent(b.read_chapters, b.chapter_count)" :stroke-width="5" :show-text="false" class="book-progress" />
        </div>
      </div>
    </section>

    <!-- 决策 37：主页全局 AI 对话（阅读之外，Skill/RAG 资产辅助） -->
    <GlobalChatPanel
      v-model:input="aiInput"
      :messages="globalAi.messages.value"
      :streaming="globalAi.streaming.value"
      :stream-error="globalAi.streamError.value"
      :collapsed="aiPanelCollapsed"
      :unread="aiUnread"
      @send="globalAi.send()"
      @abort="globalAi.abort()"
      @clear="globalAi.clear()"
      @delete-session="onDeleteAiSession"
      @copy="globalAi.copy"
      @toggle-collapse="toggleAiPanel"
    />
  </div>
</template>

<style scoped>
.home { display: flex; height: 100%; min-width: 0; }
.recent-panel {
  width: 300px; flex-shrink: 0; border-right: 1px solid var(--border-color);
  padding: 18px 16px; overflow-y: auto; background: var(--bg-color);
}
.panel-head { display: flex; align-items: baseline; justify-content: space-between; margin-bottom: 14px; }
.panel-head h2 { margin: 0; font-size: 16px; }
.panel-count { font-size: 12px; color: var(--text-secondary); }
.recent-item {
  display: flex; gap: 12px; padding: 10px; border-radius: var(--radius-md);
  cursor: pointer; transition: background 0.15s, transform 0.1s; margin-bottom: 4px;
}
.recent-item:hover { background: var(--panel-bg); transform: translateX(2px); }
.recent-cover {
  width: 46px; height: 62px; flex-shrink: 0; border-radius: 6px; overflow: hidden;
  display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, rgba(47, 111, 237, 0.25), rgba(47, 111, 237, 0.08));
  font-weight: 700; color: var(--primary-color); font-size: 16px;
  box-shadow: var(--shadow-sm);
}
.recent-cover img { width: 100%; height: 100%; object-fit: cover; }
.recent-body { flex: 1; min-width: 0; }
.recent-title {
  margin-bottom: 4px; font-weight: 600; font-size: 13px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.recent-line { margin-bottom: 6px; font-size: 12px; color: var(--text-secondary); line-height: 1.5; }
.recent-progress { width: 100%; }

.shelf-panel { flex: 1; min-width: 0; padding: 18px 20px; overflow-y: auto; background: var(--bg-color); }
.shelf-toolbar {
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; flex-wrap: wrap; position: sticky; top: 0; z-index: 3;
  padding-bottom: 14px; background: var(--bg-color);
}
.toolbar-left { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.shelf-title { display: flex; align-items: baseline; gap: 10px; }
.shelf-title h2 { margin: 0; font-size: 18px; }
.stats-chip { font-size: 12px; color: var(--text-secondary); display: inline-flex; align-items: center; gap: 6px; }
.stats-chip .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; margin-left: 2px; }
.dot.done { background: var(--success); }
.dot.reading { background: var(--primary-color); }
.toolbar-right { display: flex; align-items: center; gap: 10px; }
.search-wrap { position: relative; }
.search-input { width: 250px; }
.search-hits {
  position: absolute; top: calc(100% + 4px); left: 0; right: 0; z-index: 50;
  background: var(--card-bg); border: 1px solid var(--border-color); border-radius: var(--radius-md);
  box-shadow: var(--shadow-md); max-height: 320px; overflow-y: auto;
}
.search-hit { padding: 8px 10px; cursor: pointer; border-bottom: 1px solid var(--border-color); }
.search-hit:last-child { border-bottom: none; }
.search-hit:hover { background: var(--panel-bg); }
.hit-title { font-size: 12.5px; font-weight: 700; color: var(--text-color); }
.hit-chapter { font-weight: 400; color: var(--text-secondary); margin-left: 6px; }
.hit-snippet {
  font-size: 12px; color: var(--text-secondary); margin-top: 2px; line-height: 1.6;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.search-hits-empty { padding: 10px; font-size: 12.5px; color: var(--text-secondary); text-align: center; }
.tag-filter { width: 150px; }
.search-icon { font-size: 13px; }
.drag-hint { font-size: 12px; color: var(--text-secondary); }

.shelf-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 20px; margin-top: 6px; }
.book-card {
  position: relative; border: 1px solid var(--border-color); border-radius: var(--radius-md);
  padding: 12px; cursor: pointer; display: flex; flex-direction: column;
  background: var(--card-bg); transition: box-shadow 0.18s, border-color 0.18s, transform 0.12s;
  box-shadow: var(--shadow-sm);
}
.book-card:hover {
  border-color: color-mix(in srgb, var(--primary-color) 55%, var(--border-color));
  box-shadow: var(--shadow-md); transform: translateY(-3px);
}
.book-card.is-dragging { opacity: 0.45; }
.book-card.is-drag-over { border-color: var(--primary-color); transform: translateY(-4px); box-shadow: 0 8px 24px rgba(47, 111, 237, 0.22); }

.status-badge {
  position: absolute; top: 8px; left: 8px; z-index: 4;
  font-size: 10px; font-weight: 600; padding: 2px 8px; border-radius: 10px;
  color: #fff; letter-spacing: 0.5px;
}
.status-badge.done { background: rgba(103, 194, 58, 0.9); }
.status-badge.reading { background: rgba(47, 111, 237, 0.9); }
.status-badge.todo { background: rgba(138, 145, 159, 0.88); }

.book-actions { position: absolute; top: 6px; right: 6px; z-index: 4; display: flex; gap: 4px; opacity: 0; transition: opacity 0.15s; }
.book-card:hover .book-actions { opacity: 1; }
.book-action-btn {
  width: 26px; height: 26px; line-height: 1; border: none; border-radius: 6px;
  cursor: pointer; background: rgba(0, 0, 0, 0.45); color: #fff; font-size: 13px;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.2);
}
.book-action-btn:hover { background: var(--primary-color); }
.book-action-btn.danger:hover { background: var(--danger); }

.book-cover {
  height: 168px; display: flex; align-items: center; justify-content: center;
  background: var(--panel-bg); border-radius: 8px; overflow: hidden; user-select: none;
}
.cover-img { width: 100%; height: 100%; object-fit: cover; border-radius: 8px; pointer-events: none; transition: transform 0.25s ease; }
.book-card:hover .cover-img { transform: scale(1.04); }
.cover-placeholder {
  width: 100%; height: 100%; display: flex; flex-direction: column; gap: 6px;
  align-items: center; justify-content: center;
  background: linear-gradient(150deg, rgba(47, 111, 237, 0.18), rgba(47, 111, 237, 0.05) 55%, rgba(103, 194, 58, 0.08));
}
.cover-letter { font-size: 42px; font-weight: 800; color: color-mix(in srgb, var(--primary-color) 80%, #fff); line-height: 1; }
.cover-fmt { font-size: 10px; font-weight: 700; letter-spacing: 2px; color: var(--text-secondary); }
.book-title {
  margin-top: 10px; font-weight: 600; font-size: 14px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; user-select: none;
}

.book-tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 8px; min-height: 20px; }
.tag-chip {
  display: inline-block; max-width: 100%; padding: 1px 8px; border-radius: 10px;
  font-size: 11px; line-height: 16px; background: var(--primary-soft);
  color: var(--primary-color); cursor: pointer; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.tag-chip:hover { background: color-mix(in srgb, var(--primary-color) 24%, transparent); }
.tag-chip.active { background: var(--primary-color); color: #fff; }
.tag-empty { font-size: 12px; color: var(--text-secondary); }

.book-read-info { margin-top: 8px; font-size: 12px; color: var(--text-secondary); line-height: 1.5; }
.read-chapters { font-weight: 600; color: var(--text-color); }
.latest-chapter { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; word-break: break-all; }
.book-progress { margin-top: 10px; }
.book-progress :deep(.el-progress-bar__outer) { border-radius: 3px; }
.book-progress :deep(.el-progress-bar__inner) { border-radius: 3px; }

.tag-editor .el-select { margin-bottom: 8px; }
.tag-select-spacer { height: 44px; }
.tag-editor-actions { display: flex; justify-content: flex-end; gap: 6px; }

.empty-block {
  color: var(--text-secondary); padding: 48px 0; text-align: center;
  display: flex; flex-direction: column; align-items: center; gap: 6px;
}
.empty-icon { font-size: 40px; margin-bottom: 6px; opacity: 0.8; }
.empty-sub { font-size: 12px; opacity: 0.75; }
</style>
