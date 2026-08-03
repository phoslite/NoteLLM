/**
 * 图谱边的颜色/宽度映射工具（全局谱系图与书内知识图谱共用）。
 * 颜色随系统明暗主题自适应，保证在浅色/深色画布上都清晰可见。
 */

/** 当前是否暗色主题（跟随系统 prefers-color-scheme）。 */
export function isDarkCanvas(): boolean {
  return typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: dark)').matches
}

/**
 * 边的颜色映射：强度越高越不透明，并区分亮/暗背景保证可见性。
 * - 普通关联：蓝色（暗色下提亮），alpha 0.55 → 0.95
 * - 最密切关联（isBest）：红色（暗色下用亮红）
 */
export function edgeStrokeColor(strength: number, isBest: boolean): string {
  const alpha = Math.round((0.55 + Math.min(0.4, strength / 50)) * 100) / 100
  if (isBest) return isDarkCanvas() ? '#ff6b5e' : '#e0382e'
  return isDarkCanvas() ? `rgba(102, 172, 255, ${alpha})` : `rgba(31, 92, 205, ${alpha})`
}

/** 书内知识图谱边的颜色（亮/暗自适应）。 */
export function kpEdgeColor(): string {
  return isDarkCanvas() ? 'rgba(178, 188, 204, 0.85)' : 'rgba(70, 78, 92, 0.85)'
}
/** 谱系图边的端点：返回字符串 id 的 source/target。
 * 注意：ECharts graph 的 links 必须用「字符串 id」匹配节点，
 * 数字会被当作节点数组下标（见 echarts Graph.addEdge），导致边被静默丢弃。 */
export interface LinkEndpoint {
  source: string
  target: string
  directed: boolean
}

export function linkEndpoints(e: { book_a: number; book_b: number; direction: string; from_book: number | null }): LinkEndpoint {
  const directed = e.direction !== '无' && e.from_book != null && (e.from_book === e.book_a || e.from_book === e.book_b)
  if (directed) {
    const source = e.from_book as number
    return { source: String(source), target: String(source === e.book_a ? e.book_b : e.book_a), directed: true }
  }
  return { source: String(e.book_a), target: String(e.book_b), directed: false }
}

/** 每本书「关系最密切」的边集合（用于加粗/红色强调）。 */
export function bestEdgeSet(edges: { id: number; book_a: number; book_b: number; strength: number }[]): Set<number> {
  const best: Record<number, number> = {}
  for (const e of edges) {
    best[e.book_a] = Math.max(best[e.book_a] ?? 0, e.strength)
    best[e.book_b] = Math.max(best[e.book_b] ?? 0, e.strength)
  }
  return new Set(
    edges.filter((e) => e.strength >= (best[e.book_a] ?? 0) - 0.01 || e.strength >= (best[e.book_b] ?? 0) - 0.01).map((e) => e.id),
  )
}