<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import MdRender from '@/components/MdRender.vue'
import { deleteAssetItem, getBookAsset, getTask, summarizeBook } from '@/api/rag'
import { deleteBook, getBook } from '@/api/books'
import type { AssetEntry, BookAssetView, BookDetail } from '@/types'

const route = useRoute()
const router = useRouter()
const bookId = Number(route.params.bookId)

const book = ref<BookDetail | null>(null)
const asset = ref<BookAssetView | null>(null)
const loading = ref(false)
const busy = ref(false)
const taskMsg = ref('')
const active = ref<string[]>(['rag-summary', 'rag-keypoints', 'skill-list'])
const expandedChunks = ref<Set<number>>(new Set())

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

async function refresh() {
  loading.value = true
  try {
    const [detail, assetResult] = await Promise.allSettled([getBook(bookId), getBookAsset(bookId)])
    book.value = detail.status === 'fulfilled' ? detail.value : null
    asset.value = assetResult.status === 'fulfilled' ? assetResult.value : null
  } finally {
    loading.value = false
  }
}

function mergedCount(entry: AssetEntry<unknown> | null | undefined) {
  const content = entry?.content as Record<string, unknown> | undefined
  const ids = content?.merged_book_ids
  return Array.isArray(ids) && ids.length ? ids.length : 0
}

function toggleChunk(i: number) {
  const next = new Set(expandedChunks.value)
  if (next.has(i)) next.delete(i)
  else next.add(i)
  expandedChunks.value = next
}

async function pollTask(taskId: string) {
  for (let i = 0; i < 180; i++) {
    await sleep(1000)
    const t = await getTask(taskId)
    if (t.status === 'success') return
    if (t.status === 'failed') throw new Error(t.error || '总结失败')
  }
  throw new Error('任务超时')
}

async function runSummarize() {
  busy.value = true
  taskMsg.value = 'AI 总结中…'
  try {
    const { task_id } = await summarizeBook(bookId)
    await pollTask(task_id)
    await refresh()
    active.value = ['rag-summary', 'rag-keypoints', 'skill-list']
    ElMessage.success('总结完成')
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    busy.value = false
    taskMsg.value = ''
  }
}

async function removeItem(
  kind: 'rag' | 'skill',
  section: 'key_points' | 'chunks' | 'skills',
  index: number,
) {
  busy.value = true
  try {
    await deleteAssetItem(bookId, kind, section, index)
    ElMessage.success('已删除')
    await refresh()
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    busy.value = false
  }
}

async function removeBook() {
  try {
    await ElMessageBox.confirm(
      `确认从资产库移除「${book.value?.title ?? bookId}」？将同时删除其 RAG/Skill 资产与书籍文件，不可恢复。`,
      '移除确认',
      { type: 'warning' },
    )
  } catch {
    return
  }
  busy.value = true
  try {
    await deleteBook(bookId)
    ElMessage.success('已移除该书及其 RAG/Skill 资产')
    router.back()
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    busy.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <div class="rag-detail">
    <el-card class="detail-card" shadow="never">
      <div class="detail-head">
        <el-button size="small" @click="router.back()">← 返回资产列表</el-button>
        <div class="detail-title">
          <span v-if="book" class="fmt">{{ book.format.toUpperCase() }}</span>
          <span class="name">{{ book?.title || `书籍 #${bookId}` }}</span>
          <el-tag v-if="asset" size="small" type="success">RAG/Skill v{{ asset.version }}</el-tag>
        </div>
        <div class="head-actions">
          <el-button v-if="!asset" type="primary" size="small" :loading="busy" @click="runSummarize">
            总结为 RAG/Skill
          </el-button>
          <el-button size="small" :loading="loading" @click="refresh">刷新</el-button>
          <el-button type="danger" size="small" plain :disabled="busy" @click="removeBook">
            移除书籍（含 RAG/Skill）
          </el-button>
        </div>
      </div>
      <div v-if="busy" class="busy-tip">{{ taskMsg }}</div>

      <el-empty v-if="!loading && !asset" description="暂无 RAG/Skill 资产，可点击上方按钮总结" />

      <el-collapse v-else-if="asset" v-model="active" class="collapse">
        <el-collapse-item name="rag-summary">
          <template #title>
            <span class="item-title">RAG 摘要</span>
            <el-tag v-if="mergedCount(asset.rag)" size="small" type="warning">共享 {{ mergedCount(asset.rag) }} 本书</el-tag>
          </template>
          <div class="read-area summary-block">
            <MdRender :source="asset.rag?.content.summary || '（无摘要）'" />
          </div>
        </el-collapse-item>

        <el-collapse-item name="rag-keypoints">
          <template #title>
            <span class="item-title">关键知识点（含章节/段落出处）</span>
            <el-tag size="small" type="info">{{ asset.rag?.content.key_points?.length || 0 }}</el-tag>
          </template>
          <div v-for="(k, i) in asset.rag?.content.key_points || []" :key="i" class="kp-item">
            <span class="kp-index">{{ String(i + 1).padStart(2, '0') }}</span>
            <div class="kp-body"><MdRender :source="k" /></div>
            <el-button type="danger" size="small" link :disabled="busy" @click="removeItem('rag', 'key_points', i)">
              删除
            </el-button>
          </div>
          <div v-if="!asset.rag?.content.key_points?.length" class="empty-tip">（暂无知识点）</div>
        </el-collapse-item>

        <el-collapse-item v-if="asset.rag?.content.chunks?.length" name="rag-chunks">
          <template #title>
            <span class="item-title">知识分块（段落级原文）</span>
            <el-tag size="small" type="info">{{ asset.rag?.content.chunks?.length || 0 }}</el-tag>
            <span class="chunk-hint">点击「展开」阅读全文</span>
          </template>
          <div v-for="(c, i) in asset.rag?.content.chunks || []" :key="i" class="chunk-item">
            <div class="chunk-head">
              <span class="chunk-pos">第 {{ c.chapter_index }} 章 · {{ c.chapter_title }} · {{ c.para_pos }}</span>
              <div class="chunk-actions">
                <el-button type="primary" size="small" link @click="toggleChunk(i)">
                  {{ expandedChunks.has(i) ? '收起' : '展开' }}
                </el-button>
                <el-button type="danger" size="small" link :disabled="busy" @click="removeItem('rag', 'chunks', i)">
                  删除
                </el-button>
              </div>
            </div>
            <div class="chunk-text" :class="{ open: expandedChunks.has(i) }">
              <MdRender :source="c.text" />
            </div>
            <div v-if="!expandedChunks.has(i)" class="chunk-fade"></div>
          </div>
        </el-collapse-item>

        <el-collapse-item name="skill-list">
          <template #title>
            <span class="item-title">Skill 技能</span>
            <el-tag v-if="mergedCount(asset.skill)" size="small" type="warning">共享 {{ mergedCount(asset.skill) }} 本书</el-tag>
            <el-tag size="small" type="info">{{ asset.skill?.content.skills?.length || 0 }}</el-tag>
          </template>
          <div v-for="(s, i) in asset.skill?.content.skills || []" :key="i" class="skill-item">
            <div class="skill-head">
              <span class="skill-name">{{ s.name }}</span>
              <el-button type="danger" size="small" link :disabled="busy" @click="removeItem('skill', 'skills', i)">
                删除
              </el-button>
            </div>
            <div v-if="s.applicable" class="skill-block">
              <span class="meta-tag">适用场景</span>
              <div class="read-area"><MdRender :source="s.applicable" /></div>
            </div>
            <div v-if="s.usage" class="skill-block">
              <span class="meta-tag">使用步骤</span>
              <div class="read-area"><MdRender :source="s.usage" /></div>
            </div>
            <div v-if="s.sources?.length" class="skill-block">
              <span class="meta-tag">出处</span>
              <span class="skill-sources">{{ s.sources.join('、') }}</span>
            </div>
          </div>
          <div v-if="!asset.skill?.content.skills?.length" class="empty-tip">（暂无技能条目）</div>
        </el-collapse-item>
      </el-collapse>
    </el-card>
  </div>
</template>

<style scoped>
.rag-detail { padding: 24px 28px; overflow-y: auto; height: 100%; }
.detail-card { max-width: 1200px; margin: 0 auto; }
.detail-head {
  display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-bottom: 12px;
  position: sticky; top: -24px; z-index: 5;
  background: var(--el-bg-color, #fff); padding: 10px 4px; border-radius: 8px;
}
.detail-title { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 200px; }
.detail-title .name { font-size: 16px; font-weight: 700; }
.head-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.fmt { font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; background: var(--panel-bg); border: 1px solid var(--border-color); }
.busy-tip { margin: 4px 0 10px; color: var(--primary-color); font-size: 13px; }
.collapse { border-top: none; }
.item-title { margin-right: 10px; font-weight: 600; font-size: 14px; }
.chunk-hint { font-size: 11px; color: var(--text-secondary); font-weight: 400; }

/* 阅读排版：统一字号与行高 */
.read-area { font-size: 14px; line-height: 1.95; }
.read-area :deep(p) { margin: 0.55em 0; }
.read-area :deep(ul), .read-area :deep(ol) { margin: 0.5em 0; }
.read-area :deep(h1), .read-area :deep(h2), .read-area :deep(h3), .read-area :deep(h4) { margin: 1em 0 0.5em; }
.summary-block {
  background: var(--panel-bg); border-radius: 8px; padding: 14px 18px;
  border-left: 3px solid var(--primary-color);
}

.kp-item {
  display: flex; align-items: flex-start; gap: 12px;
  padding: 12px 14px; border-bottom: 1px dashed var(--border-color);
}
.kp-item:last-child { border-bottom: none; }
.kp-index {
  flex-shrink: 0; width: 26px; height: 26px; margin-top: 3px; border-radius: 50%;
  display: inline-flex; align-items: center; justify-content: center;
  font-size: 11px; font-weight: 700; color: var(--primary-color);
  background: color-mix(in srgb, var(--primary-color) 12%, transparent);
  border: 1px solid color-mix(in srgb, var(--primary-color) 35%, transparent);
}
.kp-body { flex: 1; min-width: 0; font-size: 14px; line-height: 1.9; }

.chunk-item {
  background: var(--panel-bg); border-radius: 8px; padding: 12px 16px; margin-bottom: 12px;
  position: relative;
}
.chunk-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 8px; }
.chunk-pos { font-size: 12px; color: var(--text-secondary); }
.chunk-actions { display: flex; align-items: center; gap: 6px; flex-shrink: 0; }
.chunk-text {
  font-size: 14px; line-height: 1.95;
  max-height: 168px; overflow: hidden; transition: max-height .25s ease;
}
.chunk-text.open { max-height: none; }
.chunk-fade {
  position: absolute; left: 16px; right: 16px; bottom: 0; height: 56px;
  background: linear-gradient(transparent, var(--panel-bg));
  pointer-events: none;
}

.skill-item { background: var(--panel-bg); border-radius: 8px; padding: 14px 16px; margin-bottom: 12px; }
.skill-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; }
.skill-name { font-weight: 700; font-size: 15px; }
.skill-block { margin-top: 10px; }
.meta-tag {
  display: inline-block; font-size: 11px; font-weight: 600; color: var(--primary-color);
  background: color-mix(in srgb, var(--primary-color) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--primary-color) 30%, transparent);
  padding: 1px 8px; border-radius: 10px; margin-bottom: 6px;
}
.skill-sources { font-size: 13px; color: var(--text-secondary); }
.empty-tip { color: var(--text-secondary); font-size: 12px; padding: 8px 0; }
</style>
