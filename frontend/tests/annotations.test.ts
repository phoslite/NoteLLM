import { describe, expect, it } from 'vitest'
import { normalizeAnnotationPoints, toPoint } from '../src/utils/annotations'
import type { AnnotationElement } from '../src/types'

describe('toPoint', () => {
  it('兼容数组点', () => {
    expect(toPoint([0.1, 0.2])).toEqual([0.1, 0.2])
  })

  it('兼容旧版 {x, y} 对象点', () => {
    expect(toPoint({ x: 0.3, y: 0.4 })).toEqual([0.3, 0.4])
  })

  it('非法输入回退到原点', () => {
    expect(toPoint(null)).toEqual([0, 0])
    expect(toPoint(undefined)).toEqual([0, 0])
  })
})

describe('normalizeAnnotationPoints', () => {
  it('把旧版对象点迁移为数组点并返回新数组', () => {
    const input: AnnotationElement[] = [
      { type: 'stroke', tool: 'pen', points: [{ x: 0.1, y: 0.2 }, { x: 0.3, y: 0.4 }] },
      { type: 'text', text: 'hi', x: 0.5, y: 0.5 },
    ]
    const out = normalizeAnnotationPoints(input)
    expect(out[0].points).toEqual([[0.1, 0.2], [0.3, 0.4]])
    expect(out).not.toBe(input)
    expect(out[1]).toBe(input[1])
  })

  it('无对象点时原样返回（不触发更新）', () => {
    const input: AnnotationElement[] = [
      { type: 'stroke', tool: 'pen', points: [[0.1, 0.2]] },
    ]
    expect(normalizeAnnotationPoints(input)).toBe(input)
  })

  it('空数组安全', () => {
    expect(normalizeAnnotationPoints([])).toEqual([])
  })
})
