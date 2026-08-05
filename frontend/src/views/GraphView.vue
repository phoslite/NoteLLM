<template>
  <div class="graph-page">
    <!-- 顶部工具栏 -->
    <header class="page-head">
      <div class="head-left">
        <h2>
          <span class="title-ico">{{ view === 'global' ? '🗺️' : '📖' }}</span>
          <span>{{ view === 'global' ? '书籍谱系图' : `《${currentBook?.title ?? ''}》知识图谱` }}</span>
        </h2>
        <p v-if="view === 'global'" class="head-sub">跨书知识谱系 · 点击书籍节点进入书内图谱 · 点击连线查看关联详情</p>
        <p v-else class="head-sub">书内知识点谱系 · 章节级 / 重要段落 / 用户标记 三层粒度 · 点击节点查看跨书出现</p>
      </div>
      <div class="head-actions">
        <template v-if="view === 'global'">
          <el-button size="small" :loading="loading" @click="onRebuildGlobal">🔄 重建图谱</el-button>
          <el-button size="small" type="primary" plain :loading="syncing" @click="onSyncAssets">💾 联动沉淀</el-button>
        </template>
        <template v-else>
          <el-button size="small" @click="backToGlobal">← 返回谱系图</el-button>
          <el-button size="small" :loading="loading" @click="rebuildCurrent">🔄 重建本书图谱</el-button>
        </template>
        <el-button size="small" @click="exportPng">⬇ 导出 PNG</el-button>
      </div>
    </header>

    <!-- ================= 全局视图 ================= -->
    <template v-if="view === 'global'">
      <GraphGlobalPanel :graph="graph" :cluster-filter="clusterFilter" @cluster-change="setCluster" />

      <div ref="el" class="graph-canvas">
        <div v-if="!graph" class="canvas-hint">{{ loading ? '正在加载谱系图…' : '暂无数据' }}</div>
      </div>
    </template>

    <!-- ================= 书内视图 ================= -->
    <template v-else>
      <GraphIntraPanel :intra="intra" :level-filter="levelFilter" @level-toggle="toggleLevel" />

      <div ref="el" class="graph-canvas">
        <div v-if="!intra" class="canvas-hint">加载中…</div>
      </div>
    </template>

    <!-- 关联详情弹窗 -->
    <el-dialog v-model="detailVisible" title="书籍关联详情" width="560px" class="g-dialog">
      <template v-if="detailEdge">
        <div class="rel-pair">
          <div class="rel-book-card">
            <b><MdRender v-if="detailBooks.a" :source="detailBooks.a.title" inline /></b>
            <span v-if="detailBooks.a">领域 {{ detailBooks.a.cluster }}</span>
            <span v-else>—</span>
          </div>
          <div class="rel-arrow">{{ detailEdge.direction === '无' ? '⇄' : '→' }}</div>
          <div class="rel-book-card">
            <b><MdRender v-if="detailBooks.b" :source="detailBooks.b.title" inline /></b>
            <span v-if="detailBooks.b">领域 {{ detailBooks.b.cluster }}</span>
            <span v-else>—</span>
          </div>
        </div>
        <div class="rel-meta">
          <el-tag size="small" type="info">{{ detailEdge.relation_type }}</el-tag>
          <el-tag size="small" :type="detailEdge.direction === '无' ? 'info' : 'danger'">
            {{ detailEdge.direction === '无' ? '双向关联' : edgeDirLabel(detailEdge, nodeMapOf(graph)) }}
          </el-tag>
          <el-tag size="small" type="warning" effect="dark">强度 {{ detailEdge.strength }}</el-tag>
        </div>
        <div class="dlg-block">
          <div class="dlg-label">关联原因</div>
          <div v-if="detailEdge.reasons.length" class="reason-list">
            <span v-for="(r, i) in detailEdge.reasons" :key="i" class="reason-tag"><MdRender :source="r" inline /></span>
          </div>
          <p v-else class="empty">—</p>
        </div>
        <div v-if="detailEdge.user_feedback" class="dlg-block">
          <div class="dlg-label">人工反馈</div>
          <el-tag size="small" type="success"><MdRender :source="detailEdge.user_feedback" inline /></el-tag>
        </div>
        <div class="feedback-row">
          <el-button size="small" type="success" @click="feedback('确认')">确认关联</el-button>
          <el-button size="small" type="warning" @click="feedback('忽略')">忽略关联</el-button>
          <span class="fb-strength">
            修改强度
            <el-input-number v-model="strengthInput" :min="0" :max="100" size="small" />
            <el-button size="small" type="primary" @click="feedback('修改')">应用</el-button>
          </span>
        </div>
      </template>
    </el-dialog>

    <!-- 知识点详情：跨书出现 -->
    <el-dialog v-model="kpDetailVisible" title="知识点详情" width="640px" class="g-dialog">
      <template v-if="kpDetail">
        <div class="kp-hero">
          <div class="kp-headline">
            <h3 class="kp-title"><MdRender :source="kpDetail.source.title" inline /></h3>
            <el-tag size="small">{{ kpDetail.source.level }}</el-tag>
          </div>
          <p class="kv">出自：《{{ currentBook?.title ?? '' }}》</p>
          <p class="kp-summary"><MdRender :source="kpDetail.source.summary || '（无摘要）'" /></p>
        </div>
        <div class="dlg-block">
          <div class="dlg-label">还出现在 {{ kpDetail.total }} 本书<template v-if="kpLoading">（检索中…）</template></div>
          <div v-if="kpDetail.books.length" class="appear-list">
            <div v-for="b in kpDetail.books" :key="b.book_id" class="appear-item">
              <div class="appear-head">
                <b><MdRender :source="b.title" inline /></b>
                <el-tag size="small">{{ b.matched_count }} 处命中</el-tag>
                <el-button size="small" type="primary" link @click="switchKpBook(b.book_id)">查看本书图谱</el-button>
              </div>
              <ul v-if="b.matched_kps.length" class="mini-list">
                <li v-for="kp in b.matched_kps.slice(0, 5)" :key="kp.id">
                  <MdRender :source="kp.title" inline /><el-tag size="small" type="info" class="kp-level">{{ kp.level }}</el-tag>
                </li>
              </ul>
              <p v-if="b.rag_hits.length" class="rag-hit">RAG 要点：<MdRender :source="b.rag_hits[0]" inline /></p>
            </div>
          </div>
          <p v-else class="empty">暂无其他书记载该知识点</p>
        </div>
      </template>
      <template #footer>
        <el-button size="small" @click="kpDetailVisible = false">关闭</el-button>
        <el-button size="small" type="primary" @click="router.push(`/reader/${kpDetail?.source.book_id}`)">跳转阅读原文</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import type { GlobalGraph, GraphEdge, GraphNode, IntraGraph, KpNode, KnowledgeAppearsIn } from '@/types'
import { getGlobalGraph, getIntraGraph, getKnowledgeAppearsIn, rebuildGraph, rebuildBookGraph, relationFeedback, syncGraphAssets } from '@/api/graph'
import { ensureGraphLabelReady } from '@/utils/graphLabel'
import { edgeDirLabel } from '@/utils/graphEdges'
import { buildGlobalOption, buildIntraOption, nodeMapOf } from '@/utils/graphOption'
import { notifyTaskSubmitted, waitForTask } from '@/utils/task'
import MdRender from '@/components/MdRender.vue'
import GraphGlobalPanel from '@/components/graph/GraphGlobalPanel.vue'
import GraphIntraPanel from '@/components/graph/GraphIntraPanel.vue'

const router = useRouter()

const loading = ref(false)
const syncing = ref(false)
const graph = ref<GlobalGraph | null>(null)
const view = ref<'global' | 'intra'>('global')
const intra = ref<IntraGraph | null>(null)
const currentBook = ref<GraphNode | null>(null)
const clusterFilter = ref('')
const levelFilter = ref<Record<string, boolean>>({ 章节级: true, 重要段落: true, 用户标记: true })

const el = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null

const detailVisible = ref(false)
const detailEdge = ref<GraphEdge | null>(null)
const detailBooks = ref<{ a: GraphNode | null; b: GraphNode | null }>({ a: null, b: null })
const strengthInput = ref(50)
const kpDetailVisible = ref(false)
const kpDetail = ref<KnowledgeAppearsIn | null>(null)
const kpLoading = ref(false)
/** 画布元素变化（全局↔书内切换）时重建 ECharts 实例，避免渲染到已卸载的 DOM。 */
function ensureChart(): echarts.ECharts | null {
  if (!el.value) return null
  if (chart && chart.getDom() !== el.value) {
    chart.dispose()
    chart = null
  }
  if (!chart) chart = echarts.init(el.value)
  return chart
}

/** 任务轮询取消（审查 N-19）：离开页面时中止等待，避免卸载后继续轮询。 */
const taskAbort = new AbortController()

function waitTask(taskId: string, opts: { intervalMs?: number; timeoutMs?: number } = {}) {
  return waitForTask(taskId, { ...opts, signal: taskAbort.signal })
}

/** 中止轮询产生的错误在 catch 中静默忽略。 */
function isTaskAbort(err: unknown): boolean {
  return (err as Error)?.name === 'AbortError'
}

async function loadGlobal() {
  loading.value = true
  try {
    await ensureGraphLabelReady()
    const g = await getGlobalGraph()
    if (g.building && g.task_id) {
      // 懒构建后台化（决策 35）：任务完成后自动重拉
      ElMessage.info('图谱构建中…')
      notifyTaskSubmitted()
      await waitTask(g.task_id)
      graph.value = await getGlobalGraph()
    } else {
      graph.value = g
    }
    await nextTick()
    renderGlobal()
  } catch (err) {
    if (isTaskAbort(err)) return
    ElMessage.error((err as Error).message)
  } finally {
    loading.value = false
  }
}

async function onRebuildGlobal() {
  loading.value = true
  try {
    const { task_id } = await rebuildGraph()
    ElMessage.info('图谱重建任务已提交…')
    notifyTaskSubmitted()
    const t = await waitTask(task_id)
    if (t.status === 'failed') {
      ElMessage.error(`重建失败：${t.error || '未知错误'}`)
      return
    }
    const stats = (t.result ?? {}) as { books?: number; relations?: number; linked?: number }
    graph.value = await getGlobalGraph()
    await nextTick()
    renderGlobal()
    ElMessage.success(
      `图谱已重建：${stats.books ?? 0} 本 / ${stats.relations ?? 0} 条关联，联动存根 ${stats.linked ?? 0} 条`,
    )
  } catch (err) {
    if (isTaskAbort(err)) return
    ElMessage.error((err as Error).message)
  } finally {
    loading.value = false
  }
}

/** 图谱联动沉淀：受影响书籍 RAG/Skill 增量增改（本地存根 + LLM 联动）。 */
async function onSyncAssets() {
  syncing.value = true
  try {
    const { task_id } = await syncGraphAssets()
    ElMessage.info('图谱资产联动任务已提交…')
    notifyTaskSubmitted()
    const t = await waitTask(task_id)
    if (t.status === 'failed') {
      ElMessage.error(`联动失败：${t.error || '未知错误'}`)
      return
    }
    const result = (t.result ?? {}) as { stubs?: number; llm_updated?: number; domain_terms?: number }
    await loadGlobal()
    ElMessage.success(
      `联动完成：存根 ${result.stubs ?? 0} 条 / LLM 更新 ${result.llm_updated ?? 0} 本 / 术语补水 ${result.domain_terms ?? 0} 条`,
    )
  } catch (err) {
    if (isTaskAbort(err)) return
    ElMessage.error((err as Error).message)
  } finally {
    syncing.value = false
  }
}

function setCluster(name: string) {
  clusterFilter.value = name
  renderGlobal()
}

function toggleLevel(level: string) {
  levelFilter.value[level] = !levelFilter.value[level]
  renderIntra()
}

function backToGlobal() {
  view.value = 'global'
  currentBook.value = null
  intra.value = null
  nextTick(() => renderGlobal())
}

async function openIntraBook(node: GraphNode) {
  loading.value = true
  try {
    await ensureGraphLabelReady()
    currentBook.value = node
    const g = await getIntraGraph(node.id)
    if (g.building && g.task_id) {
      // 书内图谱懒构建后台化：任务完成后重拉
      ElMessage.info('本书知识图谱构建中…')
      notifyTaskSubmitted()
      await waitTask(g.task_id)
      intra.value = await getIntraGraph(node.id)
    } else {
      intra.value = g
    }
    view.value = 'intra'
    await nextTick()
    renderIntra()
  } catch (err) {
    if (isTaskAbort(err)) return
    ElMessage.error((err as Error).message)
  } finally {
    loading.value = false
  }
}

async function rebuildCurrent() {
  if (!currentBook.value) return
  loading.value = true
  try {
    const bookId = currentBook.value.id
    const { task_id } = await rebuildBookGraph(bookId)
    ElMessage.info('本书知识图谱重建任务已提交…')
    notifyTaskSubmitted()
    const t = await waitTask(task_id)
    if (t.status === 'failed') {
      ElMessage.error(`重建失败：${t.error || '未知错误'}`)
      return
    }
    intra.value = await getIntraGraph(bookId)
    await nextTick()
    renderIntra()
    ElMessage.success('本书知识图谱已重建')
  } catch (err) {
    if (isTaskAbort(err)) return
    ElMessage.error((err as Error).message)
  } finally {
    loading.value = false
  }
}

/* ---------- 知识点跨书出现 ---------- */
async function openKpDetail(kp: KpNode) {
  kpDetail.value = null
  kpDetailVisible.value = true
  kpLoading.value = true
  try {
    kpDetail.value = await getKnowledgeAppearsIn(kp.id)
  } catch (err) {
    if (isTaskAbort(err)) return
    ElMessage.error((err as Error).message)
  } finally {
    kpLoading.value = false
  }
}

async function switchKpBook(bookId: number) {
  kpDetailVisible.value = false
  const node = graph.value?.nodes.find((n) => n.id === bookId)
  if (node) {
    await openIntraBook(node)
    return
  }
  await loadGlobal()
  const found = graph.value?.nodes.find((n) => n.id === bookId)
  if (found) await openIntraBook(found)
}

/* ---------- 全局谱系图渲染 ---------- */
function renderGlobal() {
  const inst = ensureChart()
  if (!inst || !graph.value) return
  inst.setOption(buildGlobalOption(graph.value, clusterFilter.value), true)
  inst.off('click')
  inst.on('click', (p: any) => {
    if (p.dataType === 'node' && p.data.book) void openIntraBook(p.data.book as GraphNode)
    if (p.dataType === 'edge' && p.data.relation) openEdgeDetail(p.data.relation)
  })
}

/* ---------- 书内知识图谱渲染 ---------- */
function renderIntra() {
  const inst = ensureChart()
  if (!inst || !intra.value) return
  inst.setOption(buildIntraOption(intra.value, levelFilter.value), true)
  inst.off('click')
  inst.on('click', (p: any) => {
    if (p.dataType === 'node' && p.data.kp) void openKpDetail(p.data.kp as KpNode)
  })
}

/* ---------- 关联详情与反馈 ---------- */
function openEdgeDetail(edge: GraphEdge) {
  if (!graph.value) return
  const nodeMap = new Map(graph.value.nodes.map((n) => [n.id, n]))
  detailEdge.value = edge
  detailBooks.value = { a: nodeMap.get(edge.book_a) ?? null, b: nodeMap.get(edge.book_b) ?? null }
  strengthInput.value = edge.strength
  detailVisible.value = true
}

async function feedback(action: string) {
  if (!detailEdge.value) return
  try {
    const strength = action === '修改' ? strengthInput.value : undefined
    await relationFeedback(detailEdge.value.id, action, strength)
    ElMessage.success(action === '确认' ? '已确认该关联' : action === '忽略' ? '已忽略该关联' : '已更新强度')
    detailVisible.value = false
    graph.value = await getGlobalGraph()
    await nextTick()
    renderGlobal()
  } catch (err) {
    ElMessage.error((err as Error).message)
  }
}

function exportPng() {
  if (!chart) return
  const url = chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#fff' })
  const a = document.createElement('a')
  a.href = url
  a.download = `${view.value === 'global' ? '书籍谱系图' : `《${currentBook.value?.title ?? ''}》知识图谱`}.png`
  a.click()
}

function resize() {
  chart?.resize()
}

onMounted(() => {
  window.addEventListener('resize', resize)
  void loadGlobal()
})

onBeforeUnmount(() => {
  taskAbort.abort()
  window.removeEventListener('resize', resize)
  chart?.dispose()
  chart = null
})
</script>
<style scoped>
.graph-page { padding: 18px 24px; height: 100%; display: flex; flex-direction: column; overflow: hidden; }

/* 顶部工具栏 */
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; flex-wrap: wrap; }
.head-left { display: flex; flex-direction: column; gap: 4px; min-width: 240px; }
.head-left h2 { margin: 0; font-size: 20px; display: flex; align-items: center; gap: 8px; }
.title-ico { font-size: 20px; }
.head-sub { color: var(--text-secondary); font-size: 12px; margin: 0; }
.head-actions { display: flex; gap: 8px; flex-wrap: wrap; }

/* 图表画布 */
.graph-canvas { position: relative; flex: 1; min-height: 420px; border: 1px solid var(--border-color); border-radius: 12px; background: var(--reading-bg); background-image: radial-gradient(var(--border-color) 1px, transparent 1px); background-size: 22px 22px; box-shadow: 0 2px 10px rgba(0, 0, 0, .04); overflow: hidden; }
.canvas-hint { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: var(--text-secondary); font-size: 14px; }

/* 关联详情弹窗 */
.g-dialog :deep(.el-dialog__title) { font-weight: 700; }
.rel-pair { display: flex; align-items: stretch; gap: 12px; padding: 16px; border: 1px solid var(--border-color); border-radius: 12px; background: var(--reading-bg); }
.rel-book-card { flex: 1; display: flex; flex-direction: column; gap: 6px; padding: 10px 12px; border-radius: 10px; background: var(--panel-bg); }
.rel-book-card b { font-size: 14px; line-height: 1.5; }
.rel-book-card span { font-size: 12px; color: var(--text-secondary); }
.rel-arrow { display: flex; align-items: center; color: var(--primary-color); font-size: 22px; font-weight: 700; }
.rel-meta { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 12px; }
.dlg-block { margin-top: 14px; }
.dlg-label { font-size: 12px; color: var(--text-secondary); margin-bottom: 6px; }
.reason-list { display: flex; flex-wrap: wrap; gap: 6px; }
.reason-tag { background: var(--panel-bg); border: 1px solid var(--border-color); border-radius: 6px; padding: 3px 9px; font-size: 12px; line-height: 1.7; }
.feedback-row { display: flex; align-items: center; gap: 10px; margin-top: 16px; padding-top: 14px; border-top: 1px dashed var(--border-color); flex-wrap: wrap; }
.fb-strength { display: flex; align-items: center; gap: 6px; margin-left: auto; }

/* 知识点详情弹窗 */
.kp-hero { padding: 14px 16px; border: 1px solid var(--border-color); border-radius: 12px; background: var(--reading-bg); }
.kp-headline { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.kp-title { margin: 0; font-size: 16px; flex: 1; }
.kp-summary { color: var(--text-secondary); font-size: 13px; line-height: 1.8; margin: 0; }
.kv { margin: 6px 0; font-size: 13px; }
.appear-list { max-height: 320px; overflow: auto; display: flex; flex-direction: column; gap: 10px; }
.appear-item { border: 1px solid var(--border-color); border-radius: 10px; padding: 10px 12px; background: var(--reading-bg); }
.appear-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.mini-list { margin: 6px 0 0 18px; font-size: 13px; line-height: 1.9; }
.kp-level { margin-left: 6px; }
.rag-hit { color: var(--text-secondary); font-size: 12px; margin: 6px 0 0; }
.empty { color: var(--text-secondary); font-size: 13px; }
</style>
