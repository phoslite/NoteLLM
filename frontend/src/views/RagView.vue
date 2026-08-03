<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import MdRender from '@/components/MdRender.vue'
import { dedupeAssets, getBookAsset, getTask, summarizeBook } from '@/api/rag'
import { listBooks, uploadBook } from '@/api/books'
import type { AssetEntry, BookAssetView, BookItem } from '@/types'

const router = useRouter()

const books = ref<BookItem[]>([])
const assets = ref<Record<number, BookAssetView>>({})
const loading = ref(false)
const pickedFile = ref<File | null>(null)
const title = ref('')
const busy = ref(false)
const busyId = ref<number | null>(null)
const taskMsg = ref('')
const submittedId = ref<number | null>(null)

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

async function refresh() {
  loading.value = true
  try {
    books.value = await listBooks()
    const entries = await Promise.all(books.value.map((b) => getBookAsset(b.id).catch(() => null)))
    const map: Record<number, BookAssetView> = {}
    books.value.forEach((b, i) => {
      if (entries[i]) map[b.id] = entries[i]!
    })
    assets.value = map
  } finally {
    loading.value = false
  }
}

function assetOf(bookId: number) {
  return assets.value[bookId] ?? null
}

function mergedCount(entry: AssetEntry<unknown> | null | undefined) {
  const content = entry?.content as Record<string, unknown> | undefined
  const ids = content?.merged_book_ids
  return Array.isArray(ids) && ids.length ? ids.length : 0
}

const submittedBook = computed(() => books.value.find((b) => b.id === submittedId.value) ?? null)
const submittedAsset = computed(() => (submittedId.value ? assetOf(submittedId.value) : null))

function openDetail(bookId: number) {
  router.push(`/rag/${bookId}`)
}

function onPick(e: Event) {
  const input = e.target as HTMLInputElement
  pickedFile.value = input.files?.[0] ?? null
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

async function runSummarize(bookId: number) {
  busyId.value = bookId
  taskMsg.value = 'AI 总结中…'
  try {
    const { task_id } = await summarizeBook(bookId)
    await pollTask(task_id)
    await refresh()
    submittedId.value = bookId
    ElMessage.success('总结完成')
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    busyId.value = null
    taskMsg.value = ''
  }
}

async function runDedupe() {
  try {
    await ElMessageBox.confirm('将按内容 hash 合并完全相同的 RAG/Skill 资产（重复导入的相同文件会合并为一条共享资产），确认执行？', '去重合并', { type: 'warning' })
  } catch {
    return
  }
  try {
    const stats = await dedupeAssets()
    ElMessage.success(`合并完成：RAG ${stats.rag} 条、Skill ${stats.skill} 条`)
    await refresh()
  } catch (err) {
    ElMessage.error((err as Error).message)
  }
}

async function startIngest() {
  if (!pickedFile.value) {
    ElMessage.warning('请先选择文件')
    return
  }
  busy.value = true
  taskMsg.value = '导入中…'
  try {
    const book = await uploadBook(pickedFile.value, title.value || undefined)
    ElMessage.success('导入成功，开始 AI 总结')
    await runSummarize(book.id)
    pickedFile.value = null
    title.value = ''
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    busy.value = false
    taskMsg.value = ''
  }
}

onMounted(refresh)
</script>

<template>
  <div class="rag-page">
    <el-card class="upload-card" shadow="never">
      <h3 class="card-title">外部资料 → RAG / Skill</h3>
      <p class="card-desc">
        上传 Markdown / PDF / TXT / EPUB 文件，AI 将自动把内容总结为可检索的 RAG 摘要与可复用的技能（Skill），
        并在原资产上增量更新（version + 1）。
      </p>
      <div class="upload-row">
        <label class="file-pick">
          <input type="file" accept=".md,.markdown,.pdf,.txt,.epub" @change="onPick" />
          <span class="file-btn">选择文件</span>
          <span class="file-name" :class="{ muted: !pickedFile }">
            {{ pickedFile ? pickedFile.name : '未选择文件（支持 .md / .pdf / .txt / .epub）' }}
          </span>
        </label>
        <el-input v-model="title" placeholder="标题（可选）" style="width: 240px" />
        <el-button type="primary" :loading="busy" @click="startIngest">上传并总结</el-button>
      </div>
      <div v-if="busy" class="busy-tip">{{ taskMsg }}</div>
    </el-card>

    <el-card v-if="submittedBook && submittedAsset" class="submitted-card" shadow="never">
      <div class="submitted-head">
        <span class="submitted-title">最近提交总结 · {{ submittedBook.title }}</span>
        <div class="head-actions">
          <el-tag size="small" type="success">v{{ submittedAsset.version }}</el-tag>
          <el-tag v-if="mergedCount(submittedAsset.rag)" size="small" type="warning">
            共享 {{ mergedCount(submittedAsset.rag) }} 本
          </el-tag>
          <el-button size="small" type="primary" link @click="openDetail(submittedBook.id)">查看完整 RAG/Skill →</el-button>
        </div>
      </div>
      <div class="submitted-fixed">
        <MdRender :source="submittedAsset.rag?.content.summary || '（无摘要）'" />
      </div>
      <div class="submitted-meta">Skill 技能 {{ submittedAsset.skill?.content.skills?.length || 0 }} 条 · 点击「查看完整 RAG/Skill」阅读全部内容</div>
    </el-card>

    <el-card class="asset-card" shadow="never">
      <template #header>
        <div class="card-head">
          <span class="card-head-title">资料资产列表</span>
          <div class="head-actions">
            <el-button size="small" @click="runDedupe">合并重复资产</el-button>
            <el-button size="small" :loading="loading" @click="refresh">刷新</el-button>
          </div>
        </div>
      </template>
      <el-empty v-if="!loading && !books.length" description="暂无资料，先上传一个文件" />
      <div v-for="b in books" :key="b.id" class="asset-row">
        <div class="asset-head">
          <span class="fmt">{{ b.format.toUpperCase() }}</span>
          <div class="main">
            <div class="title-line">
              <span class="name" :title="b.content_hash || ''">{{ b.title }}</span>
              <el-tag size="small" :type="assetOf(b.id)?.version ? 'success' : 'info'">
                {{ assetOf(b.id)?.version ? `RAG/Skill v${assetOf(b.id)!.version}` : '未总结' }}
              </el-tag>
              <el-tag v-if="mergedCount(assetOf(b.id)?.rag)" size="small" type="warning">
                共享 {{ mergedCount(assetOf(b.id)?.rag) }} 本
              </el-tag>
            </div>
            <div class="brief" :class="{ muted: !assetOf(b.id)?.rag }">
              <MdRender v-if="assetOf(b.id)?.rag" :source="assetOf(b.id)?.rag?.content.summary || '（无摘要）'" />
              <span v-else>（尚未总结）</span>
            </div>
          </div>
          <el-button size="small" :disabled="busyId === b.id" @click="openDetail(b.id)">查看完整 RAG/Skill</el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.rag-page {
  padding: 24px 28px;
  max-width: 1400px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 18px;
  overflow-y: auto;
  height: 100%;
}
.card-title { margin: 0 0 8px; font-size: 17px; }
.card-desc { margin: 0 0 16px; color: var(--text-secondary); font-size: 13px; line-height: 1.8; }
.upload-row { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.file-pick { display: inline-flex; align-items: center; gap: 10px; cursor: pointer; }
.file-pick input { display: none; }
.file-btn {
  font-size: 13px; padding: 7px 16px; border-radius: 6px; border: 1px solid var(--primary-color);
  color: var(--primary-color); background: transparent; transition: all .15s;
}
.file-pick:hover .file-btn { background: var(--primary-color); color: #fff; }
.file-name { font-size: 12px; color: var(--text-secondary); }
.file-name.muted { color: var(--text-secondary); opacity: .75; }
.busy-tip { margin-top: 10px; color: var(--primary-color); font-size: 13px; }
.card-head { display: flex; align-items: center; justify-content: space-between; }
.card-head-title { font-size: 15px; font-weight: 700; }
.head-actions { display: flex; gap: 8px; align-items: center; }
.submitted-card { border-color: var(--primary-color); }
.submitted-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 10px; }
.submitted-title { font-weight: 700; font-size: 15px; }
.submitted-fixed {
  height: 168px; overflow: hidden; position: relative;
  background: var(--panel-bg); border-radius: 8px; padding: 12px 18px;
  font-size: 14px; line-height: 1.9;
}
.submitted-fixed::after {
  content: ''; position: absolute; left: 0; right: 0; bottom: 0; height: 42px;
  background: linear-gradient(transparent, var(--panel-bg));
  pointer-events: none;
}
.submitted-meta { margin-top: 8px; font-size: 12px; color: var(--text-secondary); }
.asset-row { border-bottom: 1px solid var(--border-color); }
.asset-row:last-child { border-bottom: none; }
.asset-head { display: flex; align-items: center; gap: 14px; padding: 12px 10px; border-radius: 8px; }
.asset-head:hover { background: var(--panel-bg); }
.fmt {
  font-size: 10px; font-weight: 700; padding: 3px 7px; border-radius: 4px;
  background: var(--panel-bg); border: 1px solid var(--border-color); flex-shrink: 0;
}
.main { flex: 1; min-width: 0; }
.title-line { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.name { font-size: 15px; font-weight: 650; }
.brief {
  font-size: 13px; color: var(--text-secondary); line-height: 1.75; margin-top: 4px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.brief :deep(p) { margin: 0; }
.brief.muted { font-style: italic; }
</style>
