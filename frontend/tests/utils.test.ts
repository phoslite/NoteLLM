import { describe, expect, it } from 'vitest'
import { chapterPercent, percentOf } from '../src/utils/progress'
import { splitBlocks } from '../src/utils/content'

describe('chapterPercent', () => {
  it('按已读/总章节计算整数百分比', () => {
    expect(chapterPercent(1, 2)).toBe(50)
    expect(chapterPercent(2, 3)).toBe(67)
    expect(chapterPercent(0, 0)).toBe(0)
    expect(chapterPercent(5, 0)).toBe(0)
    expect(chapterPercent(null, 3)).toBe(0)
    expect(chapterPercent(undefined, undefined)).toBe(0)
  })
})

describe('percentOf', () => {
  it('0..1 进度转百分比', () => {
    expect(percentOf(0.432)).toBe(43)
    expect(percentOf(1)).toBe(100)
    expect(percentOf(0)).toBe(0)
    expect(percentOf(null)).toBe(0)
    expect(percentOf(undefined)).toBe(0)
  })
})

describe('splitBlocks', () => {
  it('按空行切块', () => {
    expect(splitBlocks('甲\n\n乙\n\n丙')).toEqual(['甲', '乙', '丙'])
  })

  it('丢弃空白块并 trim', () => {
    expect(splitBlocks('  甲  \n\n   \n\n乙')).toEqual(['甲', '乙'])
  })

  it('代码块内部空行不切断', () => {
    const src = '正文\n\n```py\nprint(1)\n\nprint(2)\n```\n\n结尾'
    const blocks = splitBlocks(src)
    expect(blocks).toHaveLength(3)
    expect(blocks[1]).toContain('print(1)\n\nprint(2)')
    expect(blocks[1]).toContain('```')
  })
})
