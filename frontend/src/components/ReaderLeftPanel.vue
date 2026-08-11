<script setup lang="ts">
import type { BookDetail, BookItem, ChapterItem } from '@/types'
import { chapterPercent } from '@/utils/progress'
import MdRender from '@/components/MdRender.vue'

defineProps<{
  books: BookItem[]
  book: BookDetail | null
  bookId: number
  currentChapterId: number | null
  loadError: boolean
}>()

const emit = defineEmits<{
  (e: 'select-book', id: number): void
  (e: 'select-chapter', id: number): void
  (e: 'toggle-read', chapter: ChapterItem): void
}>()

function formatBadge(format: string) {
  return (format || '?').toUpperCase()
}
</script>

<template>
  <aside class="left-panel">
    <section class="panel-section shelf-section">
      <h3 class="panel-title">书架</h3>
      <ul v-if="books.length" class="shelf-list">
        <li
          v-for="b in books"
          :key="b.id"
          :class="{ active: b.id === bookId }"
          @click="emit('select-book', b.id)"
        >
          <span class="shelf-badge">{{ formatBadge(b.format) }}</span>
          <span class="shelf-title">{{ b.title }}</span>
          <span class="shelf-progress">{{ b.read_chapters ?? 0 }}/{{ b.chapter_count }}章 {{ chapterPercent(b.read_chapters, b.chapter_count) }}%</span>
        </li>
      </ul>
      <div v-else class="empty-tip">书架为空，去主页导入书籍</div>
    </section>

    <section class="panel-section toc-section">
      <h3 class="panel-title">目录 · {{ book?.title ?? '…' }}</h3>
      <ul v-if="book" class="chapter-list">
        <li
          v-for="c in book.chapters"
          :key="c.id"
          :class="{ active: c.id === currentChapterId, read: c.read_flag }"
          @click="emit('select-chapter', c.id)"
        >
          <span class="chapter-idx">{{ c.index }}</span>
          <MdRender class="chapter-title" :source="c.title" inline />
          <button
            type="button"
            class="chapter-read-toggle"
            :class="{ done: c.read_flag }"
            :title="c.read_flag ? '取消本章已读' : '标记本章已读'"
            @click.stop="emit('toggle-read', c)"
          >
            {{ c.read_flag ? '✓' : '○' }}
          </button>
        </li>
      </ul>
      <div v-else-if="loadError" class="empty-tip">书籍加载失败，请确认后端已启动</div>
      <div v-else class="empty-tip">加载中…</div>
    </section>
  </aside>
</template>

<style scoped>
.left-panel {
  box-sizing: border-box;
  width: 25%;
  min-width: 280px;
  border-right: 1px solid var(--border-color);
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 0;
}
/* 书架区：固定在左上角，独立滚动条 */
.shelf-section {
  flex: none;
  max-height: 40%;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
}
/* 目录区：占据左下剩余区域，独立滚动条 */
.toc-section {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
  overflow-x: auto; /* E2E 四轮 #15：长章节标题横向可滚动 */
  border-top: 1px solid var(--border-color);
  padding-top: 14px;
}

.panel-title { margin: 0 0 10px; font-size: 13px; color: var(--text-secondary); font-weight: 600; letter-spacing: 0.5px; }

.shelf-list, .chapter-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.shelf-list li, .chapter-list li { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-radius: 6px; cursor: pointer; font-size: 13px; line-height: 1.4; }
.shelf-list li:hover, .chapter-list li:hover { background: var(--panel-bg); }
.shelf-list li.active, .chapter-list li.active { background: var(--primary-color); color: #fff; }

.shelf-badge { flex: none; font-size: 11px; font-weight: 700; padding: 2px 5px; border-radius: 4px; background: var(--panel-bg); color: var(--text-secondary); border: 1px solid var(--border-color); }
.shelf-list li.active .shelf-badge { background: rgba(255,255,255,0.2); color: #fff; border-color: transparent; }
.shelf-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.shelf-progress { flex: none; font-size: 13px; color: var(--text-secondary); }
.shelf-list li.active .shelf-progress { color: rgba(255,255,255,0.85); }
.chapter-list li.active .chapter-idx,
.chapter-list li.active .chapter-title,
.chapter-list li.active .chapter-read-toggle { color: rgba(255,255,255,0.92); } /* E2E 二轮：蓝底灰字副标题对比度 1.44:1 → 白字 */

.chapter-list li { align-items: flex-start; }
.chapter-list li.read { color: var(--text-secondary); }
.chapter-read-toggle {
  flex: none;
  border: none;
  background: none;
  cursor: pointer;
  font-size: 13px;
  line-height: 1;
  padding: 2px 4px;
  border-radius: 4px;
  color: var(--text-secondary);
  /* E2E 四轮 #15：点击热区 >= 24x24 */
  min-width: 24px;
  min-height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.chapter-read-toggle:hover { background: var(--panel-bg); }
.chapter-read-toggle.done { color: var(--primary-color); font-weight: 700; }
.chapter-idx { flex: none; min-width: 20px; color: var(--text-secondary); }
.chapter-title { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.empty-tip { color: var(--text-secondary); font-size: 13px; padding: 6px 2px; }
</style>
