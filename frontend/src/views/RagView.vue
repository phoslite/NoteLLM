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
const ragKeys = computed(() => submittedAsset.value?.rag?.content.key_points ?? [])
const ragChunks = computed(() => submittedAsset.value?.rag?.content.chunks ?? [])
const skillItems = computed(() => submittedAsset.value?.skill?.content.skills ?? [])
const skillDomains = computed(() => submittedAsset.value?.skill?.content.domains ?? [])
const skillUsage = computed(() => submittedAsset.value?.skill?.content.usage ?? '')

function dismissSubmitted() {
  submittedId.value = null
}

function openDetail(bookId: number) {
  router.push(`/rag/${bookId}`)
}

function onPick(e: Event) {
  const input = e.target as HTMLInputElement
  pickedFile.value = input.files?.[0] ?? null
}

function onDrop(e: DragEvent) {
  const file = e.dataTransfer?.files?.[0]
  if (file) pickedFile.value = file
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
    const res = await uploadBook(pickedFile.value, title.value || undefined)
    ElMessage.success('导入成功，开始 AI 总结')
    await runSummarize(res.id)
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
      <div class="upload-head">
        <div class="upload-icon">📄</div>
        <div class="upload-info">
          <h3 class="card-title">外部资料 → RAG / Skill</h3>
          <p class="card-desc">
            上传 Markdown / PDF / TXT / EPUB 文件，AI 将自动把内容总结为可检索的 RAG 摘要与可复用的技能（Skill），
            并在原资产上增量更新（version + 1）。
          </p>
        </div>
      </div>
      <label
        class="upload-zone"
        :class="{ active: pickedFile }"
        @dragover.prevent
        @drop.prevent="onDrop"
      >
        <input type="file" accept=".md,.markdown,.pdf,.txt,.epub" @change="onPick" />
        <span class="zone-icon">{{ pickedFile ? '📎' : '📂' }}</span>
        <span class="zone-main">
          <span class="zone-hint">{{ pickedFile ? '已选择文件' : '点击选择文件，或将文件拖入此处' }}</span>
          <span class="zone-file" :class="{ muted: !pickedFile }">
            {{ pickedFile ? pickedFile.name : '支持 .md / .pdf / .txt / .epub' }}
          </span>
        </span>
      </label>
      <div class="upload-row">
        <el-input v-model="title" placeholder="标题（可选）" style="width: 260px" />
        <el-button type="primary" round :loading="busy" @click="startIngest">上传并总结</el-button>
      </div>
      <div v-if="busy" class="busy-tip">⏳ {{ taskMsg }}</div>
    </el-card>

    <el-card v-if="submittedBook && submittedAsset" class="submitted-card" shadow="never">
      <div class="submitted-head">
        <div class="submitted-title-wrap">
          <span class="submitted-icon">✅</span>
          <span class="submitted-title">最近提交总结 · {{ submittedBook.title }}</span>
          <el-tag size="small" type="success">RAG/Skill v{{ submittedAsset.version }}</el-tag>
        </div>
        <div class="submitted-actions">
          <el-button size="small" type="primary" link @click="openDetail(submittedBook.id)">查看完整 RAG/Skill →</el-button>
          <el-button size="small" link @click="dismissSubmitted">✕ 关闭</el-button>
        </div>
      </div>
      <div class="submitted-window">
        <section class="detail-sec">
          <h4 class="sec-title">📝 RAG 摘要</h4>
          <div class="sec-body">
            <MdRender :source="submittedAsset.rag?.content.summary || '（无摘要）'" />
          </div>
        </section>
        <div v-if="ragKeys.length || skillItems.length || skillDomains.length || skillUsage" class="detail-grid">
          <section v-if="ragKeys.length" class="detail-sec">
            <h4 class="sec-title">📌 关键知识点（{{ ragKeys.length }}）</h4>
            <ol class="kp-list">
              <li v-for="(kp, i) in ragKeys" :key="i"><MdRender :source="kp" /></li>
            </ol>
          </section>
          <section v-if="skillItems.length || skillDomains.length || skillUsage" class="detail-sec">
            <h4 class="sec-title">🛠️ Skill 技能（{{ skillItems.length }}）</h4>
            <div v-if="skillDomains.length" class="skill-meta">
              <span v-for="d in skillDomains" :key="d" class="chip">{{ d }}</span>
            </div>
            <div v-for="(sk, i) in skillItems" :key="i" class="skill-item">
              <div class="skill-name">{{ sk.name }}</div>
              <div v-if="sk.applicable" class="skill-sub"><MdRender :source="sk.applicable" /></div>
              <div v-if="sk.usage" class="skill-sub"><MdRender :source="sk.usage" /></div>
            </div>
            <div v-if="skillUsage" class="skill-usage"><MdRender :source="skillUsage" /></div>
          </section>
        </div>
        <section v-if="ragChunks.length" class="detail-sec">
          <h4 class="sec-title">🧩 知识分块（{{ ragChunks.length }} 段）</h4>
          <div v-for="(c, i) in ragChunks" :key="i" class="chunk-item">
            <div class="chunk-meta">第{{ c.chapter_index }}章 · {{ c.chapter_title }} · {{ c.para_pos }}</div>
            <div class="chunk-text"><MdRender :source="c.text" /></div>
          </div>
        </section>
      </div>
      <div class="submitted-meta">{{ ragKeys.length }} 条关键知识点 · {{ ragChunks.length }} 段知识分块 · {{ skillItems.length }} 个 Skill 技能</div>
    </el-card>

    <el-card class="asset-card" shadow="never">
      <template #header>
        <div class="card-head">
          <span class="card-head-title">📚 资料资产列表</span>
          <span class="head-sub" v-if="books.length">共 {{ books.length }} 本书 · {{ books.filter((b) => assetOf(b.id)?.version).length }} 本已总结</span>
          <div class="head-actions">
            <el-button size="small" @click="runDedupe">合并重复资产</el-button>
            <el-button size="small" :loading="loading" @click="refresh">刷新</el-button>
          </div>
        </div>
      </template>
      <el-empty v-if="!loading && !books.length" description="暂无资料，先上传一个文件" />
      <div v-for="b in books" :key="b.id" class="asset-row" :class="{ summarized: !!assetOf(b.id)?.version }">
        <div class="asset-rail" :class="assetOf(b.id)?.version ? 'has' : ''"></div>
        <span class="fmt">{{ b.format.toUpperCase() }}</span>
        <div class="main">
          <div class="title-line">
            <span class="name" :title="b.title">{{ b.title }}</span>
            <el-tag size="small" :type="assetOf(b.id)?.version ? 'success' : 'info'">
              {{ assetOf(b.id)?.version ? `RAG/Skill v${assetOf(b.id)!.version}` : '未总结' }}
            </el-tag>
            <el-tag v-if="mergedCount(assetOf(b.id)?.rag)" size="small" type="warning">
              共享 {{ mergedCount(assetOf(b.id)?.rag) }} 本
            </el-tag>
          </div>
          <div class="brief" :class="{ muted: !assetOf(b.id)?.rag }">
            <MdRender v-if="assetOf(b.id)?.rag" :source="assetOf(b.id)?.rag?.content.summary || '（无摘要）'" />
            <span v-else>（尚未总结，点击右侧「AI 总结」生成 RAG 与 Skill）</span>
          </div>
        </div>
        <div class="row-actions">
          <el-button v-if="!assetOf(b.id)?.version" type="primary" size="small" plain :loading="busyId === b.id" @click="runSummarize(b.id)">
            AI 总结
          </el-button>
          <el-button v-else size="small" type="primary" link @click="openDetail(b.id)">查看完整 RAG/Skill →</el-button>
        </div>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.rag-page {
  padding: 24px 28px 40px;
  max-width: 1400px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 18px;
  min-height: 100%;
  background: var(--bg-color);
}
.upload-card { border-radius: var(--radius-lg); }
.upload-head { display: flex; align-items: center; gap: 14px; margin-bottom: 14px; }
.upload-icon {
  width: 52px; height: 52px; flex-shrink: 0; border-radius: 12px;
  display: flex; align-items: center; justify-content: center; font-size: 26px;
  background: var(--primary-soft);
}
.upload-info { flex: 1; min-width: 0; }
.card-title { margin: 0 0 6px; font-size: 17px; }
.card-desc { margin: 0; color: var(--text-secondary); font-size: 13px; line-height: 1.8; }
.upload-zone {
  display: flex; align-items: center; gap: 14px;
  padding: 14px 18px;
  border: 1.5px dashed var(--border-color);
  border-radius: 12px;
  background: var(--panel-bg);
  cursor: pointer;
  transition: border-color .15s, background .15s;
}
.upload-zone:hover {
  border-color: var(--primary-color);
  background: color-mix(in srgb, var(--primary-soft) 45%, var(--panel-bg));
}
.upload-zone.active { border-color: var(--success); }
.upload-zone input { display: none; }
.zone-icon { font-size: 22px; flex-shrink: 0; }
.zone-main { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.zone-hint { font-size: 12.5px; font-weight: 600; }
.zone-file {
  font-size: 12px; color: var(--text-secondary);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.zone-file.muted { opacity: .75; }
.upload-row { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; }
.busy-tip { margin-top: 10px; color: var(--primary-color); font-size: 13px; }

.card-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.card-head-title { font-size: 15px; font-weight: 700; }
.head-sub { font-size: 12px; color: var(--text-secondary); }
.head-actions { display: flex; gap: 8px; align-items: center; }

.submitted-card { border-color: color-mix(in srgb, var(--success) 45%, var(--border-color)); border-radius: var(--radius-lg); }
.submitted-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 10px; }
.submitted-title-wrap { display: flex; align-items: center; gap: 8px; }
.submitted-icon { font-size: 15px; }
.submitted-title { font-weight: 700; font-size: 15px; }
.submitted-actions { display: flex; align-items: center; gap: 10px; }
.submitted-window {
  background: var(--panel-bg); border-radius: 8px; padding: 16px 18px;
  display: flex; flex-direction: column; gap: 16px;
}
.detail-sec { min-width: 0; }
.sec-title { margin: 0 0 8px; font-size: 13px; font-weight: 700; }
.sec-body { font-size: 13.5px; line-height: 1.9; }
.sec-body :deep(p), .kp-list :deep(p), .skill-sub :deep(p), .skill-usage :deep(p), .chunk-text :deep(p) { margin: 0; }
.detail-grid {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 16px; align-items: start;
}
.kp-list { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 8px; font-size: 13px; line-height: 1.8; }
.skill-meta { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
.chip { font-size: 11px; padding: 2px 9px; border-radius: 999px; background: var(--primary-soft); color: var(--primary-color); }
.skill-item { padding: 9px 11px; background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 8px; }
.skill-item + .skill-item { margin-top: 8px; }
.skill-name { font-weight: 700; font-size: 13px; }
.skill-sub { font-size: 12.5px; color: var(--text-secondary); margin-top: 4px; line-height: 1.7; }
.skill-usage { font-size: 12.5px; color: var(--text-secondary); margin-top: 8px; line-height: 1.7; }
.chunk-item { padding: 10px 12px; background: var(--card-bg); border: 1px solid var(--border-color); border-radius: 8px; }
.chunk-item + .chunk-item { margin-top: 8px; }
.chunk-meta { font-size: 11.5px; color: var(--text-secondary); margin-bottom: 4px; }
.chunk-text { font-size: 13px; line-height: 1.8; }
.submitted-meta { margin-top: 10px; font-size: 12px; color: var(--text-secondary); }

.asset-card { border-radius: var(--radius-lg); }
.asset-row {
  display: flex; align-items: center; gap: 14px; padding: 14px 12px;
  border-radius: var(--radius-md); border: 1px solid transparent;
  transition: background 0.15s, border-color 0.15s, box-shadow 0.15s;
  position: relative;
}
.asset-row + .asset-row { margin-top: 8px; }
.asset-row:hover {
  background: var(--panel-bg);
  border-color: var(--border-color);
  box-shadow: var(--shadow-sm);
}
.asset-rail {
  position: absolute; left: 0; top: 12px; bottom: 12px; width: 3px;
  border-radius: 2px; background: var(--border-color);
}
.asset-rail.has { background: var(--success); }
.fmt {
  font-size: 10px; font-weight: 700; padding: 3px 7px; border-radius: 4px;
  background: var(--panel-bg); border: 1px solid var(--border-color); flex-shrink: 0;
  letter-spacing: 0.5px;
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
.row-actions { flex-shrink: 0; }
</style>
