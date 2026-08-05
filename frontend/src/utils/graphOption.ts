/**
 * 图谱 ECharts option 拼装（审查 P0-A1：从 GraphView 视图内抽出为纯函数，可单测）。
 *
 * - buildGlobalOption：书籍级谱系图（聚类分层 + 最强边强调 + 方向箭头 + 领域图例）；
 * - buildIntraOption：书内知识图谱（章节级/重要段落/用户标记三层 + 顺序链）。
 * 视图层只负责 chart 生命周期与 click 事件注册，数据 → option 的转换全部在本模块。
 */
import type { EChartsOption } from 'echarts'
import type { GlobalGraph, GraphEdge, GraphNode, IntraGraph, KpNode } from '@/types'
import { LABEL_FONT_SIZE, labelRichFormatter, renderTooltipHtml } from './graphLabel'
import { bestEdgeSet, edgeDirLabel, edgeStrokeColor, kpEdgeColor, linkEndpoints } from './graphEdges'

/** 领域调色板（10 色轮换，与图例/节点颜色共用）。 */
export const PALETTE = ['#409eff', '#67c23a', '#e6a23c', '#f56c6c', '#909399', '#9b59b6', '#2ecc71', '#e74c3c', '#16a085', '#8e44ad']
/** 书内知识点层级颜色。 */
export const LEVEL_COLOR: Record<string, string> = { 章节级: '#409eff', 重要段落: '#f56c6c', 用户标记: '#e6a23c' }

export function truncateLabel(s: string, n: number): string {
  return (s || '').length > n ? `${(s || '').slice(0, n)}…` : s || ''
}

/** 领域 → 调色板颜色（按领域出现顺序稳定映射）。 */
export function clusterColorFor(clusterNames: string[], name: string): string {
  const i = clusterNames.indexOf(name)
  return PALETTE[i % PALETTE.length] ?? '#909399'
}

/** 书籍级谱系图 option：clusterFilter 空串=全部领域。 */
export function buildGlobalOption(
  g: GlobalGraph,
  clusterFilter: string,
): EChartsOption {
  const nodeMap = new Map(g.nodes.map((n) => [n.id, n]))
  let nodes = g.nodes
  if (clusterFilter) nodes = g.nodes.filter((n) => n.cluster === clusterFilter)
  const ids = new Set(nodes.map((n) => n.id))
  const edges = g.edges.filter((e) => ids.has(e.book_a) && ids.has(e.book_b))
  const clusterNames = [...new Set(nodes.map((n) => n.cluster))]

  // 每本书的「关系最密切」边（加粗/红色强调）
  const bestSet = bestEdgeSet(edges)

  const data = nodes.map((n) => {
    const label = labelRichFormatter(n.title, LABEL_FONT_SIZE)
    return {
      id: String(n.id),
      name: n.title,
      value: n.chapter_count,
      symbolSize: 16 + Math.min(24, Math.log2((n.chapter_count || 1) + 1) * 5),
      itemStyle: { color: clusterColorFor(clusterNames, n.cluster) },
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

  return {
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
    legend: { top: 4, data: clusterNames, textStyle: { fontSize: 11 } },
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
        categories: clusterNames.map((name) => ({ name, itemStyle: { color: clusterColorFor(clusterNames, name) } })),
      },
    ],
    // echarts 5.6 类型未声明 graph 系列的 large/progressive（运行时支持），故此处整体断言为 EChartsOption
  } as EChartsOption
}

/** 书内知识图谱 option：levelFilter 控制三层粒度显隐。 */
export function buildIntraOption(
  kp: IntraGraph,
  levelFilter: Record<string, boolean>,
): EChartsOption {
  const chapters = new Map(kp.chapters.map((c) => [c.id, c]))
  const nodes: KpNode[] = kp.nodes.filter((n) => levelFilter[n.level] ?? true)
  const ids = new Set(nodes.map((n) => n.id))
  const edges = kp.edges.filter((e) => ids.has(e.from) && ids.has(e.to))

  const data = nodes.map((n) => {
    const label = labelRichFormatter(n.title, LABEL_FONT_SIZE)
    return {
      id: String(n.id),
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

  return {
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => {
        if (p.dataType === 'edge') return `${p.data.source} → ${p.data.target}`
        const n: KpNode = p.data.kp
        const ch = n.chapter_id ? chapters.get(n.chapter_id) : null
        const pos = n.para_pos ? `第 ${n.para_pos} 段` : ''
        const summary = renderTooltipHtml(truncateLabel(n.summary || '（无摘要）', 180), true)
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
    // echarts 5.6 类型未声明 graph 系列的 large/progressive（运行时支持），故此处整体断言为 EChartsOption
  } as EChartsOption
}

/** 关联详情弹窗的节点映射（GraphView 弹窗用）。 */
export function nodeMapOf(g: GlobalGraph | null): Map<number, GraphNode> {
  return new Map(g?.nodes.map((n) => [n.id, n]) ?? [])
}

export type { GraphEdge }
