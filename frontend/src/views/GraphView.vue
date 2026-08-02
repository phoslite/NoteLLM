<template>
  <div class="graph-page">
    <div class="graph-head">
      <h2>{{ view === 'global' ? '书籍谱系图' : `《${currentBook?.title ?? ''}》知识图谱` }}</h2>
      <div class="head-actions">
        <el-button v-if="view === 'intra'" size="small" @click="backToGlobal">← 返回谱系图</el-button>
        <el-button v-if="view === 'global'" size="small" :loading="loading" @click="onRebuildGlobal">🔄 重建图谱</el-button>
        <el-button v-if="view === 'global'" size="small" type="primary" plain :loading="syncing" @click="onSyncAssets">💾 联动沉淀</el-button>
        <el-button v-if="view === 'intra'" size="small" :loading="loading" @click="rebuildCurrent">🔄 重建本书图谱</el-button>
        <el-button size="small" @click="exportPng">⬇ 导出 PNG</el-button>
      </div>
    </div>

    <!-- 全局视图：聚类筛选 + 图 -->
    <template v-if="view === 'global'">
      <div class="filter-bar">
        <el-check-tag :checked="clusterFilter === ''" @change="setCluster('')">全部</el-check-tag>
        <el-check-tag
          v-for="c in graph?.clusters ?? []"
          :key="c.name"
          :checked="clusterFilter === c.name"
          @change="setCluster(c.name)"
        >{{ c.name }}（{{ c.book_count }}）</el-check-tag>
        <span v-if="graph && graph.nodes.length === 0" class="empty-tip">暂无书籍，请先导入书籍</span>
      </div>
      <div ref="el" class="graph-canvas"></div>
    </template>

    <!-- 书内视图 -->
    <template v-else>
      <div class="filter-bar">
        <span class="filter-label">知识点层级：</span>
        <el-check-tag :checked="levelFilter['章节级']" @change="toggleLevel('章节级')">章节级</el-check-tag>
        <el-check-tag :checked="levelFilter['重要段落']" @change="toggleLevel('重要段落')">重要段落</el-check-tag>
        <el-check-tag :checked="levelFilter['用户标记']" @change="toggleLevel('用户标记')">用户标记</el-check-tag>
        <span class="empty-tip">{{ intra ? `${intra.nodes.length} 个知识点 / ${intra.edges.length} 条关系` : '' }}</span>
      </div>
      <div ref="el" class="graph-canvas"></div>
    </template>

    <!-- 关联详情弹窗 -->
    <el-dialog v-model="detailVisible" title="书籍关联详情" width="480px">
      <template v-if="detailEdge">
        <div class="rel-line">
          <b>{{ detailBooks.a?.title }}</b>
          <el-tag size="small" :type="detailEdge.direction === '无' ? 'info' : 'danger'" class="dir-tag">
            {{ detailEdge.direction === '无' ? '双向关联' : edgeDirLabel(detailEdge, new Map(graph?.nodes.map((n) => [n.id, n]) ?? [])) }}
          </el-tag>
          <b>{{ detailBooks.b?.title }}</b>
        </div>
        <p>关联类型：{{ detailEdge.relation_type }}　|　关联强度：<b>{{ detailEdge.strength }}</b></p>
        <p class="rel-reasons">
          关联原因：
          <span v-for="(r, i) in detailEdge.reasons" :key="i" class="reason-tag">{{ r }}</span>
          <span v-if="!detailEdge.reasons.length">—</span>
        </p>
        <p v-if="detailEdge.user_feedback">人工反馈：<el-tag size="small">{{ detailEdge.user_feedback }}</el-tag></p>
        <div class="feedback-row">
          <el-button size="small" type="success" @click="feedback('确认')">确认关联</el-button>
          <el-button size="small" type="warning" @click="feedback('忽略')">忽略关联</el-button>
          <span class="fb-strength">
            修改强度：
            <el-input-number v-model="strengthInput" :min="0" :max="100" size="small" />
            <el-button size="small" type="primary" @click="feedback('修改')">应用</el-button>
          </span>
        </div>
      </template>
    </el-dialog>

    <!-- 知识点详情：跨书出现 -->
    <el-dialog v-model="kpDetailVisible" title="知识点详情" width="580px">
      <template v-if="kpDetail">
        <p class="kp-title"><b>{{ kpDetail.source.title }}</b></p>
        <p class="kv">层级：{{ kpDetail.source.level }}　|　出自：《{{ currentBook?.title ?? '' }}》</p>
        <p class="kp-summary">{{ kpDetail.source.summary || '（无摘要）' }}</p>
        <el-divider />
        <p class="kv"><b>还出现在 {{ kpDetail.total }} 本书</b><span v-if="kpLoading" class="empty">　检索中…</span></p>
        <div v-if="kpDetail.books.length" class="appear-list">
          <div v-for="b in kpDetail.books" :key="b.book_id" class="appear-item">
            <div class="appear-head">
              <b>《{{ b.title }}》</b>
              <el-tag size="small">{{ b.matched_count }} 处命中</el-tag>
              <el-button size="small" type="primary" link @click="switchKpBook(b.book_id)">查看本书图谱</el-button>
            </div>
            <ul v-if="b.matched_kps.length" class="mini-list">
              <li v-for="kp in b.matched_kps.slice(0, 5)" :key="kp.id">
                {{ kp.title }}<el-tag size="small" type="info" class="kp-level">{{ kp.level }}</el-tag>
              </li>
            </ul>
            <p v-if="b.rag_hits.length" class="rag-hit">RAG 要点：{{ b.rag_hits[0] }}</p>
          </div>
        </div>
        <p v-else class="empty">暂无其他书记载该知识点</p>
      </template>
      <template #footer>
        <el-button size="small" @click="kpDetailVisible = false">关闭</el-button>
        <el-button size="small" type="primary" @click="router.push(`/reader/${kpDetail?.source.book_id}`)">跳转阅读原文</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import type { GlobalGraph, GraphEdge, GraphNode, IntraGraph, KpNode, KnowledgeAppearsIn } from '@/types'
import { getGlobalGraph, getIntraGraph, getKnowledgeAppearsIn, rebuildGraph, rebuildBookGraph, relationFeedback, syncGraphAssets } from '@/api/graph'

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

const PALETTE = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c', '#909399', '#9b59b6', '#2ecc71', '#e74c3c', '#16a085', '#8e44ad']
const LEVEL_COLOR: Record<string, string> = { 章节级: '#409eff', 重要段落: '#f56c6c', 用户标记: '#e6a23c' }

function truncate(s: string, n: number) {
  return (s || '').length > n ? `${(s || '').slice(0, n)}…` : s || ''
}

function clusterColor(name: string): string {
  const names = [...new Set((graph.value?.clusters ?? []).map((c) => c.name))]
  const i = names.indexOf(name)
  return PALETTE[i % PALETTE.length] ?? '#909399'
}

async function loadGlobal() {
  loading.value = true
  try {
    graph.value = await getGlobalGraph()
    await nextTick()
    renderGlobal()
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    loading.value = false
  }
}

async function onRebuildGlobal() {
  loading.value = true
  try {
    const stats = await rebuildGraph()
    graph.value = await getGlobalGraph()
    await nextTick()
    renderGlobal()
    ElMessage.success(
      `图谱已重建：${stats.books} 本 / ${stats.relations} 条关联，联动存根 ${stats.linked ?? 0} 条`,
    )
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    loading.value = false
  }
}

/** 图谱联动沉淀：受影响书籍 RAG/Skill 增量增改（本地存根 + LLM 联动）。 */
async function onSyncAssets() {
  syncing.value = true
  try {
    const result = await syncGraphAssets()
    await loadGlobal()
    ElMessage.success(
      `联动完成：存根 ${result.stubs} 条 / LLM 更新 ${result.llm_updated} 本 / 术语补水 ${result.domain_terms} 条`,
    )
  } catch (err) {
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
    currentBook.value = node
    intra.value = await getIntraGraph(node.id)
    view.value = 'intra'
    await nextTick()
    renderIntra()
  } catch (err) {
    ElMessage.error((err as Error).message)
  } finally {
    loading.value = false
  }
}

async function rebuildCurrent() {
  if (!currentBook.value) return
  loading.value = true
  try {
    intra.value = await rebuildBookGraph(currentBook.value.id)
    await nextTick()
    renderIntra()
    ElMessage.success('本书知识图谱已重建')
  } catch (err) {
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

/** 有向边：返回箭头 source→target（无方向返回 book_a→book_b 且 directed=false）。 */
function edgeEndpoints(e: GraphEdge, nodeMap: Map<number, GraphNode>) {
  const directed = e.direction !== '无' && e.from_book != null && (e.from_book === e.book_a || e.from_book === e.book_b)
  if (directed) {
    const source = e.from_book as number
    return { source, target: source === e.book_a ? e.book_b : e.book_a, directed: true }
  }
  return { source: e.book_a, target: e.book_b, directed: false }
}

/** 关联方向展示文案（详情弹窗用）。 */
function edgeDirLabel(edge: GraphEdge, nodeMap: Map<number, GraphNode>): string {
  const { source, target, directed } = edgeEndpoints(edge, nodeMap)
  if (!directed) return '双向关联'
  return `${nodeMap.get(source)?.title ?? source} → ${nodeMap.get(target)?.title ?? target}`
}

/* ---------- 全局谱系图渲染 ---------- */
function renderGlobal() {
  if (!el.value || !graph.value) return
  const g = graph.value
  const nodeMap = new Map(g.nodes.map((n) => [n.id, n]))
  let nodes = g.nodes
  if (clusterFilter.value) nodes = g.nodes.filter((n) => n.cluster === clusterFilter.value)
  const ids = new Set(nodes.map((n) => n.id))
  const edges = g.edges.filter((e) => ids.has(e.book_a) && ids.has(e.book_b))

  // 每本书的「关系最密切」边
  const best: Record<number, number> = {}
  for (const e of edges) {
    best[e.book_a] = Math.max(best[e.book_a] ?? 0, e.strength)
    best[e.book_b] = Math.max(best[e.book_b] ?? 0, e.strength)
  }
  const bestSet = new Set(edges.filter((e) => e.strength >= (best[e.book_a] ?? 0) - 0.01 || e.strength >= (best[e.book_b] ?? 0) - 0.01).map((e) => e.id))

  const data = nodes.map((n) => ({
    id: n.id,
    name: n.title,
    value: n.chapter_count,
    symbolSize: 16 + Math.min(24, Math.log2((n.chapter_count || 1) + 1) * 5),
    itemStyle: { color: clusterColor(n.cluster) },
    category: n.cluster,
    book: n,
  }))

  const links = edges.map((e) => {
    const { source, target, directed } = edgeEndpoints(e, nodeMap)
    return {
      source,
      target,
      value: e.strength,
      relation: e,
      isBest: bestSet.has(e.id),
      lineStyle: {
        width: bestSet.has(e.id) ? 4 + e.strength / 20 : 1.5 + e.strength / 40,
        color: bestSet.has(e.id) ? '#f56c6c' : `rgba(64, 158, 255, ${0.3 + e.strength / 200})`,
        curveness: 0.08,
      },
      edgeLabel: {
        show: bestSet.has(e.id) && e.strength >= 20,
        formatter: () => `${e.strength}分 ${e.reasons[0] ?? ''}`.trim(),
        fontSize: 10,
        color: '#c0392b',
      },
      symbol: directed ? ['none', 'arrow'] : 'none',
    }
  })

  if (!chart) chart = echarts.init(el.value)
  chart.setOption(
    {
      tooltip: {
        trigger: 'item',
        formatter: (p: any) => {
          if (p.dataType === 'edge') {
            const r = p.data.relation
            return `<b>${nodeMap.get(r.book_a)?.title} ↔ ${nodeMap.get(r.book_b)?.title}</b><br/>强度：${r.strength}｜类型：${r.relation_type}<br/>原因：${(r.reasons ?? []).join('、') || '—'}<br/>方向：${edgeDirLabel(r, nodeMap)}`
          }
          const b: GraphNode = p.data.book
          return `<b>${b.title}</b><br/>领域：${b.cluster}｜章节：${b.chapter_count}<br/>状态：${b.status}${b.graph_built ? '' : '<br/>（图谱未构建）'}<br/>点击查看本书知识图谱`
        },
      },
      legend: { top: 4, data: [...new Set(nodes.map((n) => n.cluster))], textStyle: { fontSize: 11 } },
      series: [
        {
          type: 'graph',
          layout: 'force',
          roam: true,
          draggable: true,
          data,
          links,
          force: { repulsion: 220, edgeLength: [80, 200], gravity: 0.12 },
          label: { show: true, position: 'bottom', fontSize: 10, formatter: (p: any) => truncate(p.data.name, 9) },
          lineStyle: { color: 'source' },
          emphasis: { focus: 'adjacency', lineStyle: { width: 5 } },
          categories: [...new Set(nodes.map((n) => n.cluster))].map((name) => ({ name, itemStyle: { color: clusterColor(name) } })),
        },
      ],
    },
    true,
  )
  chart.off('click')
  chart.on('click', (p: any) => {
    if (p.dataType === 'node' && p.data.book) void openIntraBook(p.data.book as GraphNode)
    if (p.dataType === 'edge' && p.data.relation) openEdgeDetail(p.data.relation)
  })
}

/* ---------- 书内知识图谱渲染 ---------- */
function renderIntra() {
  if (!el.value || !intra.value) return
  const kp = intra.value
  const chapters = new Map(kp.chapters.map((c) => [c.id, c]))
  const nodes: KpNode[] = kp.nodes.filter((n) => levelFilter.value[n.level] ?? true)
  const ids = new Set(nodes.map((n) => n.id))
  const edges = kp.edges.filter((e) => ids.has(e.from) && ids.has(e.to))

  const data = nodes.map((n) => ({
    id: n.id,
    name: n.title,
    value: n.importance,
    symbolSize: 12 + n.importance * 3,
    itemStyle: { color: LEVEL_COLOR[n.level] ?? '#909399' },
    level: n.level,
    kp: n,
  }))
  const links = edges.map((e) => ({
    source: e.from,
    target: e.to,
    value: e.strength,
    lineStyle: { width: 1.5 + e.strength / 40, color: 'rgba(96, 98, 102, 0.6)', curveness: 0.1 },
    symbol: ['none', 'arrow'],
  }))

  if (!chart) chart = echarts.init(el.value)
  chart.setOption(
    {
      tooltip: {
        trigger: 'item',
        formatter: (p: any) => {
          if (p.dataType === 'edge') return `${p.data.source} → ${p.data.target}`
          const n: KpNode = p.data.kp
          const ch = n.chapter_id ? chapters.get(n.chapter_id) : null
          const pos = n.para_pos ? `第 ${n.para_pos} 段` : ''
          return `<b>${n.title}</b><br/>层级：${n.level}｜重要度：${n.importance}<br/>出处：${ch ? `第 ${ch.index} 章${pos ? ' · ' + pos : ''}` : '—'}<br/>${truncate(n.summary || '（无摘要）', 120)}<br/>点击跳转阅读原文`
        },
      },
      legend: { top: 4, data: ['章节级', '重要段落', '用户标记'], textStyle: { fontSize: 11 } },
      series: [
        {
          type: 'graph',
          layout: 'force',
          roam: true,
          draggable: true,
          data,
          links,
          force: { repulsion: 160, edgeLength: [60, 140], gravity: 0.08 },
          label: { show: true, position: 'bottom', fontSize: 10, formatter: (p: any) => truncate(p.data.name, 8) },
          lineStyle: { color: 'source' },
          emphasis: { focus: 'adjacency', lineStyle: { width: 4 } },
        },
      ],
    },
    true,
  )
  chart.off('click')
  chart.on('click', (p: any) => {
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
  window.removeEventListener('resize', resize)
  chart?.dispose()
  chart = null
})
</script>

<style scoped>
.graph-page { padding: 16px 20px; height: 100%; display: flex; flex-direction: column; overflow: hidden; }
.graph-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.graph-head h2 { margin: 0; font-size: 18px; }
.head-actions { display: flex; gap: 8px; }
.filter-bar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding-bottom: 8px; }
.filter-label { color: var(--text-secondary); font-size: 13px; }
.empty-tip { color: var(--text-secondary); font-size: 13px; margin-left: auto; }
.graph-canvas { flex: 1; border: 1px solid var(--border-color); border-radius: 8px; min-height: 420px; }
.rel-line { display: flex; align-items: center; gap: 8px; }
.dir-tag { margin: 0 4px; }
.rel-reasons { line-height: 1.9; }
.reason-tag { display: inline-block; background: var(--el-fill-color-light, #f0f2f5); border-radius: 4px; padding: 1px 6px; margin-right: 6px; font-size: 12px; }
.feedback-row { display: flex; align-items: center; gap: 10px; margin-top: 14px; flex-wrap: wrap; }
.kp-title { font-size: 15px; }
.kp-summary { color: var(--text-secondary); font-size: 13px; line-height: 1.7; }
.appear-list { max-height: 300px; overflow: auto; display: flex; flex-direction: column; gap: 10px; }
.appear-item { border: 1px solid var(--border-color); border-radius: 8px; padding: 8px 10px; }
.appear-head { display: flex; align-items: center; gap: 8px; }
.kp-level { margin-left: 6px; }
.rag-hit { color: var(--text-secondary); font-size: 12px; margin: 4px 0 0; }
.fb-strength { display: flex; align-items: center; gap: 6px; }
</style>
