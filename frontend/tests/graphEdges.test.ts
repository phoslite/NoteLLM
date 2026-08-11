import { describe, expect, it } from 'vitest'
import { bestEdgeSet, edgeStrokeColor, kpEdgeColor, linkEndpoints } from '../src/utils/graphEdges'

describe('linkEndpoints', () => {
  it('无方向：book_a → book_b，directed=false', () => {
    expect(linkEndpoints({ book_a: 4, book_b: 8, direction: '无', from_book: null })).toEqual({ source: '4', target: '8', directed: false })
  })

  it('有向且 from_book=book_a：箭头从 book_a 指向 book_b', () => {
    expect(linkEndpoints({ book_a: 13, book_b: 15, direction: '发展', from_book: 13 })).toEqual({ source: '13', target: '15', directed: true })
  })

  it('有向且 from_book=book_b：箭头从 book_b 指向 book_a', () => {
    expect(linkEndpoints({ book_a: 13, book_b: 15, direction: '发展', from_book: 15 })).toEqual({ source: '15', target: '13', directed: true })
  })

  it('from_book 不是任一端点：视为无方向', () => {
    expect(linkEndpoints({ book_a: 13, book_b: 15, direction: '发展', from_book: 99 })).toEqual({ source: '13', target: '15', directed: false })
  })

  it('端点必须是字符串 id（ECharts 数字 source/target 会被当作节点数组下标导致边被丢弃）', () => {
    const { source, target } = linkEndpoints({ book_a: 4, book_b: 8, direction: '无', from_book: null })
    expect(typeof source).toBe('string')
    expect(typeof target).toBe('string')
  })
})

describe('bestEdgeSet', () => {
  it('返回每本书强度最高的边 id（非任何端点最强的边被排除）', () => {
    const edges = [
      { id: 1, book_a: 1, book_b: 2, strength: 10 },
      { id: 2, book_a: 1, book_b: 3, strength: 20 },
      { id: 3, book_a: 2, book_b: 3, strength: 15 },
    ]
    expect(bestEdgeSet(edges)).toEqual(new Set([2, 3]))
  })

  it('空边集返回空集合', () => {
    expect(bestEdgeSet([])).toEqual(new Set())
  })
})

describe('edgeStrokeColor', () => {
  it('最密切关联用红色（亮色）', () => {
    expect(edgeStrokeColor(50, true)).toBe('#e0382e')
  })

  it('普通关联用蓝色，透明度随强度升高（0.68 起，白底对比度 >=3.6:1）', () => {
    expect(edgeStrokeColor(10, false)).toBe('rgba(31, 92, 205, 0.71)')
    expect(edgeStrokeColor(50, false)).toBe('rgba(31, 92, 205, 0.82)')
    expect(edgeStrokeColor(100, false)).toBe('rgba(31, 92, 205, 0.95)')
  })
})

describe('kpEdgeColor', () => {
  it('书内边为灰色（亮色）', () => {
    expect(kpEdgeColor()).toBe('rgba(70, 78, 92, 0.85)')
  })
})
