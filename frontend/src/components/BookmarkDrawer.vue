<template>
  <el-drawer v-model="visible" title="书签" size="420px" :append-to-body="false">
    <div class="bm-actions">
      <el-button size="small" type="primary" @click="addCurrent">＋ 添加当前页/章节书签</el-button>
      <el-input v-model="newTitle" size="small" placeholder="书签名（留空用默认）" style="margin-top: 8px" />
      <el-input v-model="newGroup" size="small" placeholder="分组（可选，如：分析）" style="margin-top: 8px" />
    </div>

    <el-empty v-if="!bookmarks.length" description="暂无书签" />

    <template v-else>
      <div v-for="group in groups" :key="group" class="bm-group">
        <div class="bm-group-title">
          <span>{{ group || '未分组' }}</span>
          <span class="bm-count">{{ groupCount(group) }}</span>
        </div>
        <div v-for="bm in groupItems(group)" :key="bm.id" class="bm-item">
          <div class="bm-head">
            <span class="bm-title" @click="jump(bm)">{{ bm.title }}</span>
            <span class="bm-actions">
              <el-button size="small" text @click="jump(bm)">定位</el-button>
              <el-button size="small" text @click="edit(bm)">编辑</el-button>
              <el-button size="small" text type="danger" @click="remove(bm)">删除</el-button>
            </span>
          </div>
          <div v-if="bm.note" class="bm-note">{{ bm.note }}</div>
          <div class="bm-loc">
            <span v-if="bm.page_index != null">第 {{ bm.page_index }} 页</span>
            <span v-else-if="chapterTitle(bm)">第 {{ chapterTitle(bm)!.index }} 章 {{ chapterTitle(bm)!.title }}</span>
            <span v-else>未定位章节</span>
            <span class="bm-time">{{ fmt(bm.created_at) }}</span>
          </div>
        </div>
      </div>
    </template>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createBookmark, deleteBookmark, listBookmarks, updateBookmark } from '@/api/annotations'
import type { BookmarkItem, ChapterItem } from '@/types'

const props = defineProps<{
  bookId: number
  chapters: ChapterItem[]
  /** 当前章节（添加书签定位用）。 */
  currentChapterId: number | null
  /** PDF 按页阅读时的当前页号。 */
  currentPageIndex: number | null
}>()

const emit = defineEmits<{ (e: 'jump', bookmark: BookmarkItem): void }>()

const visible = defineModel<boolean>({ required: true })
const bookmarks = ref<BookmarkItem[]>([])
const newTitle = ref('')
const newGroup = ref('')

const groups = computed(() => {
  const names = new Set(bookmarks.value.map((b) => b.group_name || ''))
  return [...names].sort((a, b) => (a || 'zzz').localeCompare(b || 'zzz'))
})

function groupItems(group: string) {
  return bookmarks.value.filter((b) => (b.group_name || '') === group)
}

function groupCount(group: string) {
  return groupItems(group).length
}

function chapterTitle(bm: BookmarkItem) {
  return props.chapters.find((c) => c.id === bm.chapter_id)
}

function fmt(iso: string | null) {
  if (!iso) return ''
  const d = new Date(iso)
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

async function refresh() {
  try {
    bookmarks.value = await listBookmarks(props.bookId)
  } catch (err) {
    ElMessage.error((err as Error).message)
  }
}

async function addCurrent() {
  if (!props.currentChapterId && props.currentPageIndex == null) {
    ElMessage.warning('请先打开一个章节/页面再添加书签')
    return
  }
  try {
    const title = newTitle.value.trim()
    const group = newGroup.value.trim()
    await createBookmark(props.bookId, {
      chapter_id: props.currentChapterId,
      page_index: props.currentPageIndex,
      para_pos: null,
      title: title || (props.currentPageIndex != null ? `第 ${props.currentPageIndex} 页` : '当前章节'),
      group_name: group,
    })
    newTitle.value = ''
    newGroup.value = ''
    await refresh()
    ElMessage.success('书签已保存')
  } catch (err) {
    ElMessage.error((err as Error).message)
  }
}

async function edit(bm: BookmarkItem) {
  try {
    const { value } = await ElMessageBox.prompt(
      '书签名',
      '编辑书签',
      { inputValue: bm.title, confirmButtonText: '保存', cancelButtonText: '取消' },
    )
    await updateBookmark(bm.id, { title: value ?? bm.title })
    await refresh()
  } catch {
    /* 取消 */
  }
}

async function remove(bm: BookmarkItem) {
  try {
    await ElMessageBox.confirm(`删除书签「${bm.title}」？`, '提示', { type: 'warning' })
    await deleteBookmark(bm.id)
    await refresh()
    ElMessage.success('已删除')
  } catch {
    /* 取消 */
  }
}

function jump(bm: BookmarkItem) {
  emit('jump', bm)
  visible.value = false
}

watch(visible, (v) => {
  if (v) void refresh()
})
</script>

<style scoped>
.bm-actions { margin-bottom: 12px; }
.bm-group { margin-bottom: 14px; }
.bm-group-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  font-weight: 600;
  padding: 4px 2px;
  border-bottom: 1px solid var(--border-color, #ebeef5);
}
.bm-count { font-weight: 400; color: var(--text-secondary, #909399); font-size: 12px; }
.bm-item { border: 1px solid var(--border-color, #ebeef5); border-radius: 8px; padding: 8px 10px; margin-top: 8px; }
.bm-head { display: flex; align-items: center; gap: 8px; }
.bm-title { flex: 1; font-size: 13px; font-weight: 500; cursor: pointer; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bm-title:hover { color: var(--primary-color, #409eff); }
.bm-actions { flex: none; display: flex; }
.bm-note { margin-top: 6px; font-size: 12px; color: var(--text-secondary, #909399); white-space: pre-wrap; word-break: break-word; }
.bm-loc { margin-top: 4px; font-size: 12px; color: var(--text-secondary, #909399); display: flex; justify-content: space-between; }
.bm-time { flex: none; }
</style>
