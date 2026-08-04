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
      <section v-if="graph" class="stat-grid">
        <div v-for="s in statCards" :key="s.label" class="stat-card" :style="{ '--sc': s.color }">
          <span class="stat-ico">{{ s.icon }}</span>
          <div class="stat-body">
            <b>{{ s.value }}</b>
            <span>{{ s.label }}</span>
          </div>
        </div>
      </section>

      <section class="filter-bar">
        <span class="filter-label">领域筛选</span>
        <div class="cluster-tags">
          <el-check-tag :checked="clusterFilter === ''" @click="setCluster('')">全部</el-check-tag>
          <el-check-tag
            v-for="c in graph?.clusters ?? []"
            :key="c.name"
            :checked="clusterFilter === c.name"
            @click="setCluster(c.name)"
          >
            {{ c.name }}<span class="count-badge">{{ c.book_count }}</span>
          </el-check-tag>
        </div>
        <span v-if="graph && graph.nodes.length === 0" class="empty-tip">暂无书籍，请先导入书籍</span>
      </section>

      <div ref="el" class="graph-canvas">
        <div v-if="!graph" class="canvas-hint">{{ loading ? '正在加载谱系图…' : '暂无数据' }}</div>
      </div>
    </template>

    <!-- ================= 书内视图 ================= -->
    <template v-else>
      <section v-if="intra" class="stat-grid stat-grid-small">
        <div class="stat-card mini"><b>{{ intraStats.chapters }}</b><span>章节</span></div>
        <div class="stat-card mini"><b>{{ intraStats.nodes }}</b><span>知识点</span></div>
        <div class="stat-card mini"><b>{{ intraStats.edges }}</b><span>关系</span></div>
        <div class="stat-card mini">
          <b>{{ Object.values(levelFilter).filter(Boolean).length }}/3</b><span>层级显示</span>
        </div>
      </section>

      <section class="filter-bar">
        <span class="filter-label">知识点层级</span>
        <div class="level-tags">
          <el-check-tag :checked="levelFilter['章节级']" @click="toggleLevel('章节级')">章节级</el-check-tag>
          <el-check-tag :checked="levelFilter['重要段落']" @click="toggleLevel('重要段落')">重要段落</el-check-tag>
          <el-check-tag :checked="levelFilter['用户标记']" @click="toggleLevel('用户标记')">用户标记</el-check-tag>
        </div>
        <span class="count-tip">{{ intra ? `${intra.nodes.length} 个知识点 / ${intra.edges.length} 条关系` : '' }}</span>
      </section>

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
            {{ detailEdge.direction === '无' ? '双向关联' : edgeDirLabel(detailEdge, new Map(graph?.nodes.map((n) => [n.id, n]) ?? [])) }}
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
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import type { GlobalGraph, GraphEdge, GraphNode, IntraGraph, KpNode, KnowledgeAppearsIn } from '@/types'
import { getGlobalGraph, getIntraGraph, getKnowledgeAppearsIn, rebuildGraph, rebuildBookGraph, relationFeedback, syncGraphAssets } from '@/api/graph'
import { LABEL_FONT_SIZE, ensureGraphLabelReady, labelRichFormatter, renderTooltipHtml } from '@/utils/graphLabel'
import { bestEdgeSet, edgeStrokeColor, kpEdgeColor, linkEndpoints } from '@/utils/graphEdges'
import { notifyTaskSubmitted, waitForTask } from '@/utils/task'
import MdRender from '@/components/MdRender.vue'

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

const globalStats = computed(() => {
  const nodes = graph.value?.nodes ?? []
  const edges = graph.value?.edges ?? []
  return {
    books: nodes.length,
    edges: edges.length,
    clusters: new Set(nodes.map((n) => n.cluster)).size,
    built: nodes.filter((n) => n.graph_built).length,
    directed: edges.filter((e) => e.direction !== '无').length,
  }
})

const statCards = computed(() => [
  { icon: '📚', label: '书籍', value: globalStats.value.books, color: '#409eff' },
  { icon: '🔗', label: '关联', value: globalStats.value.edges, color: '#67c23a' },
  { icon: '➡️', label: '有向传承', value: globalStats.value.directed, color: '#f56c6c' },
  { icon: '🗂️', label: '领域', value: globalStats.value.clusters, color: '#e6a23c' },
  { icon: '✅', label: '已建图谱', value: globalStats.value.built, color: '#9b59b6' },
])

const intraStats = computed(() => ({
  chapters: intra.value?.chapters.length ?? 0,
  nodes: intra.value?.nodes.length ?? 0,
  edges: intra.value?.edges.length ?? 0,
}))

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

async function loadGlobal() {
  loading.value = true
  try {
    await ensureGraphLabelReady()
    const g = await getGlobalGraph()
    if (g.building && g.task_id) {
      // 懒构建后台化（决策 35）：任务完成后自动重拉
      ElMessage.info('图谱构建中…')
      notifyTaskSubmitted()
      await waitForTask(g.task_id)
      graph.value = await getGlobalGraph()
    } else {
      graph.value = g
    }
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
    const { task_id } = await rebuildGraph()
    ElMessage.info('图谱重建任务已提交…')
    notifyTaskSubmitted()
    const t = await waitForTask(task_id)
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
    const t = await waitForTask(task_id)
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
      await waitForTask(g.task_id)
      intra.value = await getIntraGraph(node.id)
    } else {
      intra.value = g
    }
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
    const bookId = currentBook.value.id
    const { task_id } = await rebuildBookGraph(bookId)
    ElMessage.info('本书知识图谱重建任务已提交…')
    notifyTaskSubmitted()
    const t = await waitForTask(task_id)
    if (t.status === 'failed') {
      ElMessage.error(`重建失败：${t.error || '未知错误'}`)
      return
    }
    intra.value = await getIntraGraph(bookId)
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
/** 关联方向展示（数值端点，供 nodeMap 查书名）：方向判定复用 linkEndpoints，避免两处实现。 */
function edgeEndpoints(e: GraphEdge) {
  const { source, target, directed } = linkEndpoints(e)
  return { source: Number(source), target: Number(target), directed }
}
/** 关联方向展示文案（详情弹窗用）。 */
function edgeDirLabel(edge: GraphEdge, nodeMap: Map<number, GraphNode>): string {
  const { source, target, directed } = edgeEndpoints(edge)
  if (!directed) return '双向关联'
  return `${nodeMap.get(source)?.title ?? source} → ${nodeMap.get(target)?.title ?? target}`
}

/* ---------- 全局谱系图渲染 ---------- */
function renderGlobal() {
  const inst = ensureChart()
  if (!inst || !graph.value) return
  const g = graph.value
  const nodeMap = new Map(g.nodes.map((n) => [n.id, n]))
  let nodes = g.nodes
  if (clusterFilter.value) nodes = g.nodes.filter((n) => n.cluster === clusterFilter.value)
  const ids = new Set(nodes.map((n) => n.id))
  const edges = g.edges.filter((e) => ids.has(e.book_a) && ids.has(e.book_b))

  // 每本书的「关系最密切」边（加粗/红色强调）
  const bestSet = bestEdgeSet(edges)

  const data = nodes.map((n) => {
    const label = labelRichFormatter(n.title, LABEL_FONT_SIZE)
    return {
      id: n.id,
      name: n.title,
      value: n.chapter_count,
      symbolSize: 16 + Math.min(24, Math.log2((n.chapter_count || 1) + 1) * 5),
      itemStyle: { color: clusterColor(n.cluster) },
      category: n.cluster,
      book: n,
      label: { formatter: label.formatter, rich: label.rich },
    }
  })

  const links = edges.map((e) => {
    const { source, target, directed } = linkEndpoints(e)
    const isBest = bestSet.has(e.id)
    return {
      source,
      target,
      value: e.strength,
      relation: e,
      isBest,
      lineStyle: {
        width: isBest ? 4 + e.strength / 20 : 1.5 + e.strength / 40,
        color: edgeStrokeColor(e.strength, isBest),
        curveness: 0.08,
      },
      edgeLabel: (() => {
        const label = labelRichFormatter(`${e.strength}分 ${e.reasons[0] ?? ''}`.trim(), LABEL_FONT_SIZE, 14)
        return {
          show: bestSet.has(e.id) && e.strength >= 20,
          formatter: label.formatter,
          rich: label.rich,
          fontSize: LABEL_FONT_SIZE,
          color: '#c0392b',
        }
      })(),
      symbol: directed ? ['none', 'arrow'] : 'none',
    }
  })

  inst.setOption(
    {
      tooltip: {
        trigger: 'item',
        formatter: (p: any) => {
          if (p.dataType === 'edge') {
            const r = p.data.relation
            const reasons = (r.reasons ?? []).map((x: string) => `• ${renderTooltipHtml(x, true)}`).join('<br/>')
            return `<b>${renderTooltipHtml(nodeMap.get(r.book_a)?.title ?? '—', true)} ↔ ${renderTooltipHtml(nodeMap.get(r.book_b)?.title ?? '—', true)}</b><br/>强度：${r.strength}｜类型：${r.relation_type}<br/>方向：${edgeDirLabel(r, nodeMap)}<br/>原因：<br/>${reasons || '—'}`
          }
          const b: GraphNode = p.data.book
          return `<b>${renderTooltipHtml(b.title, true)}</b><br/>领域：${b.cluster}｜章节：${b.chapter_count}<br/>状态：${b.status}${b.graph_built ? '' : '<br/>（图谱未构建）'}<br/>点击查看本书知识图谱`
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
          large: nodes.length > 200,
          progressive: nodes.length > 200 ? 400 : 0,
          force: { repulsion: 220, edgeLength: [80, 200], gravity: 0.12 },
          label: { show: true, position: 'bottom', fontSize: LABEL_FONT_SIZE },
          lineStyle: { color: 'source' },
          emphasis: { focus: 'adjacency', lineStyle: { width: 5 } },
          categories: [...new Set(nodes.map((n) => n.cluster))].map((name) => ({ name, itemStyle: { color: clusterColor(name) } })),
        },
      ],
    },
    true,
  )
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
  const kp = intra.value
  const chapters = new Map(kp.chapters.map((c) => [c.id, c]))
  const nodes: KpNode[] = kp.nodes.filter((n) => levelFilter.value[n.level] ?? true)
  const ids = new Set(nodes.map((n) => n.id))
  const edges = kp.edges.filter((e) => ids.has(e.from) && ids.has(e.to))

  const data = nodes.map((n) => {
    const label = labelRichFormatter(n.title, LABEL_FONT_SIZE)
    return {
      id: n.id,
      name: n.title,
      value: n.importance,
      symbolSize: 12 + n.importance * 3,
      itemStyle: { color: LEVEL_COLOR[n.level] ?? '#909399' },
      level: n.level,
      kp: n,
      label: { formatter: label.formatter, rich: label.rich },
    }
  })
  const links = edges.map((e) => ({
    source: String(e.from),
    target: String(e.to),
    value: e.strength,
    lineStyle: { width: 1.5 + e.strength / 40, color: kpEdgeColor(), curveness: 0.1 },
    symbol: ['none', 'arrow'],
  }))

  inst.setOption(
    {
      tooltip: {
        trigger: 'item',
        formatter: (p: any) => {
          if (p.dataType === 'edge') return `${p.data.source} → ${p.data.target}`
          const n: KpNode = p.data.kp
          const ch = n.chapter_id ? chapters.get(n.chapter_id) : null
          const pos = n.para_pos ? `第 ${n.para_pos} 段` : ''
          const summary = renderTooltipHtml(truncate(n.summary || '（无摘要）', 180), true)
          return `<b>${renderTooltipHtml(n.title, true)}</b><br/>层级：${n.level}｜重要度：${n.importance}<br/>出处：${ch ? `第 ${ch.index} 章${pos ? ' · ' + pos : ''}` : '—'}<br/>${summary}<br/>点击跳转阅读原文`
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
          large: nodes.length > 200,
          progressive: nodes.length > 200 ? 400 : 0,
          force: { repulsion: 160, edgeLength: [60, 140], gravity: 0.08 },
          label: { show: true, position: 'bottom', fontSize: LABEL_FONT_SIZE },
          lineStyle: { color: 'source' },
          emphasis: { focus: 'adjacency', lineStyle: { width: 4 } },
        },
      ],
    },
    true,
  )
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

/* 统计卡片 */
.stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(128px, 1fr)); gap: 10px; margin-bottom: 12px; }
.stat-grid-small { grid-template-columns: repeat(auto-fit, minmax(118px, 1fr)); }
.stat-card { display: flex; align-items: center; gap: 10px; padding: 10px 14px; background: var(--reading-bg); border: 1px solid var(--border-color); border-radius: 12px; box-shadow: 0 1px 4px rgba(0, 0, 0, .03); }
.stat-ico { font-size: 20px; }
.stat-body { display: flex; flex-direction: column; line-height: 1.25; }
.stat-body b { font-size: 19px; color: var(--sc, var(--primary-color)); }
.stat-body span { font-size: 12px; color: var(--text-secondary); }
.stat-card.mini { justify-content: flex-start; padding: 8px 14px; }
.stat-card.mini b { font-size: 17px; }

/* 筛选栏 */
.filter-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 2px 0 12px; }
.filter-label { color: var(--text-secondary); font-size: 13px; flex-shrink: 0; }
.cluster-tags { display: flex; gap: 6px; flex-wrap: wrap; max-height: 76px; overflow-y: auto; }
.count-badge { margin-left: 5px; font-size: 11px; opacity: .7; background: var(--panel-bg); border-radius: 999px; padding: 0 6px; }
.level-tags { display: flex; gap: 6px; flex-wrap: wrap; }
.empty-tip { color: var(--text-secondary); font-size: 13px; margin-left: auto; }
.count-tip { color: var(--text-secondary); font-size: 12px; margin-left: auto; }

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
