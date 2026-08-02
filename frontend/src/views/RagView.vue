<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getBookAsset, getTask, summarizeBook } from '@/api/rag'
import { listBooks, uploadBook } from '@/api/books'
import type { BookAssetView, BookItem } from '@/types'

const books = ref<BookItem[]>([])
const assets = ref<Record<number, BookAssetView>>({})
const loading = ref(false)
const expanded = ref<number | null>(null)
const pickedFile = ref<File | null>(null)
const title = ref('')
const busy = ref(false)
const busyId = ref<number | null>(null)
const taskMsg = ref('')

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

function toggle(bookId: number) {
  expanded.value = expanded.value === bookId ? null : bookId
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
    expanded.value = bookId
    ElMessage.success('总结完成')
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    busyId.value = null
    taskMsg.value = ''
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
        <input type="file" accept=".md,.markdown,.pdf,.txt,.epub" @change="onPick" />
        <el-input v-model="title" placeholder="标题（可选）" style="width: 260px" />
        <el-button type="primary" :loading="busy" @click="startIngest">上传并总结</el-button>
      </div>
      <div v-if="busy" class="busy-tip">{{ taskMsg }}</div>
    </el-card>

    <el-card class="asset-card" shadow="never">
      <template #header>
        <div class="card-head">
          <span>资料资产列表</span>
          <el-button size="small" :loading="loading" @click="refresh">刷新</el-button>
        </div>
      </template>
      <el-empty v-if="!loading && !books.length" description="暂无资料，先上传一个文件" />
      <div v-for="b in books" :key="b.id" class="asset-row">
        <div class="asset-head" @click="toggle(b.id)">
          <span class="fmt">{{ b.format.toUpperCase() }}</span>
          <span class="name">{{ b.title }}</span>
          <el-tag size="small" :type="assetOf(b.id)?.version ? 'success' : 'info'">
            {{ assetOf(b.id)?.version ? `RAG/Skill v${assetOf(b.id)!.version}` : '未总结' }}
          </el-tag>
        </div>

        <div v-if="expanded === b.id" class="asset-detail">
          <div v-if="assetOf(b.id)">
            <h4>RAG 摘要</h4>
            <pre class="summary">{{ assetOf(b.id)!.rag?.content.summary || '（无摘要）' }}</pre>
            <h4>关键知识点（含章节/段落出处）</h4>
            <ul class="key-points">
              <li v-for="(k, i) in assetOf(b.id)!.rag?.content.key_points || []" :key="i">{{ k }}</li>
            </ul>
            <h4>Skill 技能</h4>
            <div v-for="(s, i) in assetOf(b.id)!.skill?.content.skills || []" :key="i" class="skill-item">
              <div class="skill-name">{{ s.name }}</div>
              <div v-if="s.applicable" class="skill-meta">适用场景：{{ s.applicable }}</div>
              <pre v-if="s.usage" class="skill-usage">{{ s.usage }}</pre>
              <div v-if="s.sources?.length" class="skill-meta">出处：{{ s.sources.join('、') }}</div>
            </div>
            <div v-if="!assetOf(b.id)!.skill?.content.skills?.length" class="no-skill">（暂无技能条目）</div>
          </div>
          <div v-else>
            <el-button type="primary" size="small" :loading="busyId === b.id" @click="runSummarize(b.id)">
              总结为 RAG/Skill
            </el-button>
          </div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.rag-page { padding: 20px; display: flex; flex-direction: column; gap: 16px; overflow-y: auto; height: 100%; }
.card-title { margin: 0 0 8px; }
.card-desc { margin: 0 0 14px; color: var(--text-secondary); font-size: 13px; line-height: 1.7; }
.upload-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.busy-tip { margin-top: 10px; color: var(--primary-color); font-size: 13px; }
.card-head { display: flex; align-items: center; justify-content: space-between; }
.asset-row { border-bottom: 1px solid var(--border-color); padding: 4px 0; }
.asset-row:last-child { border-bottom: none; }
.asset-head { display: flex; align-items: center; gap: 10px; padding: 8px 4px; cursor: pointer; border-radius: 6px; }
.asset-head:hover { background: var(--panel-bg); }
.fmt { font-size: 10px; font-weight: 700; padding: 2px 6px; border-radius: 4px; background: var(--panel-bg); border: 1px solid var(--border-color); }
.name { flex: 1; font-size: 14px; }
.asset-detail { padding: 8px 12px 16px; }
.asset-detail h4 { margin: 14px 0 6px; font-size: 13px; color: var(--text-secondary); }
.summary { white-space: pre-wrap; line-height: 1.8; margin: 0; font-size: 13px; background: var(--panel-bg); padding: 10px; border-radius: 6px; }
.key-points { margin: 0; padding-left: 18px; line-height: 1.9; font-size: 13px; }
.skill-item { background: var(--panel-bg); border-radius: 6px; padding: 10px 12px; margin-bottom: 8px; }
.skill-name { font-weight: 700; font-size: 14px; }
.skill-meta { font-size: 12px; color: var(--text-secondary); margin-top: 4px; }
.skill-usage { white-space: pre-wrap; margin: 6px 0 0; font-size: 13px; line-height: 1.7; }
.no-skill { color: var(--text-secondary); font-size: 12px; }
</style>