/** 页图涂鸦数据兼容工具（需求 3.5：坐标均为相对页宽高的 0~1 归一化值）。 */

import type { AnnotationElement } from '@/types'

/** 点坐标可能为 [x, y] 数组（新版）或 {x, y} 对象（旧版数据），统一转为数组。 */
export function toPoint(p: unknown): [number, number] {
  if (Array.isArray(p)) return [Number(p[0]) || 0, Number(p[1]) || 0]
  if (p && typeof p === 'object') {
    const o = p as { x?: unknown; y?: unknown }
    return [Number(o.x) || 0, Number(o.y) || 0]
  }
  return [0, 0]
}

/** 把旧版 {x, y} 对象点迁移为 [x, y] 数组；无变化时原样返回，避免触发多余更新。 */
export function normalizeAnnotationPoints(elements: AnnotationElement[]): AnnotationElement[] {
  let changed = false
  const out = elements.map((item) => {
    if (item.type !== 'stroke' || !Array.isArray(item.points) || !item.points.length) return item
    const hasObjectPoint = item.points.some((p) => !Array.isArray(p))
    if (!hasObjectPoint) return item
    changed = true
    return { ...item, points: item.points.map((p) => toPoint(p)) }
  })
  return changed ? out : elements
}
