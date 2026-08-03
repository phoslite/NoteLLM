import { describe, expect, it, beforeAll } from 'vitest'
import {
  ensureGraphLabelReady,
  formulaToImage,
  labelRichFormatter,
  splitLabelSegments,
  stripMarkdown,
  truncateLabelText,
} from '../src/utils/graphLabel'

beforeAll(async () => {
  await ensureGraphLabelReady()
}, 20000)

describe('stripMarkdown', () => {
  it('去除加粗/斜体/行内代码/链接/列表/引用标记', () => {
    expect(stripMarkdown('**加粗**与`代码`和*斜体*')).toBe('加粗与代码和斜体')
    expect(stripMarkdown('- 列表项')).toBe('列表项')
    expect(stripMarkdown('1. 有序项')).toBe('有序项')
    expect(stripMarkdown('[链接](https://x.com)')).toBe('链接')
    expect(stripMarkdown('> 引用')).toBe('引用')
  })
})

describe('formulaToImage', () => {
  it('LaTeX → SVG data URL 与像素尺寸', () => {
    const img = formulaToImage('\\Lambda^n V')
    expect(img).not.toBeNull()
    expect(img!.url.startsWith('data:image/svg+xml')).toBe(true)
    expect(img!.width).toBeGreaterThan(0)
    expect(img!.height).toBeGreaterThan(0)
  })

  it('非法公式返回 null（回退纯文本）', () => {
    expect(formulaToImage('\\frac{')).toBeNull()
  })
})

describe('splitLabelSegments', () => {
  it('把 $...$ 公式与文本切分', () => {
    const segs = splitLabelSegments('顶层 $\\Lambda^n V$ 一维')
    expect(segs.some((s) => s.type === 'formula')).toBe(true)
    expect(segs.filter((s) => s.type === 'text').map((s) => s.text).join('')).toContain('顶层')
  })

  it('裸 \\command 段（无 $ 定界）按公式处理', () => {
    const segs = splitLabelSegments('\\dim \\ker A = n - \\operatorname{rank} A')
    expect(segs.some((s) => s.type === 'formula')).toBe(true)
  })

  it('Markdown 标记在文本段中被清洗', () => {
    const segs = splitLabelSegments('**一段地基**：线性方程组')
    const texts = segs.filter((s) => s.type === 'text').map((s) => s.text).join('')
    expect(texts).toBe('一段地基：线性方程组')
  })
})

describe('labelRichFormatter', () => {
  it('返回 rich 图片片段与文本片段', () => {
    const out = labelRichFormatter('$\\Lambda^n V$ 与 $K$')
    expect(out.rich).toHaveProperty('img0')
    expect(out.formatter.length).toBeGreaterThanOrEqual(3)
  })

  it('长文本截断（保留尾部省略号）', () => {
    const out = labelRichFormatter('这是一个非常非常长的节点名称用于测试截断')
    const text = (out.formatter as { type: string; text: string }[])
      .filter((f) => f.type === 'text')
      .map((f) => f.text)
      .join('')
    expect(text.length).toBeLessThanOrEqual(13)
    expect(text.endsWith('…')).toBe(true)
  })

  it('空名称兜底显示 …', () => {
    const out = labelRichFormatter('')
    expect(out.formatter.length).toBe(1)
  })
})

describe('truncateLabelText', () => {
  it('超出长度加省略号', () => {
    expect(truncateLabelText('abcdefghijklmnop')).toBe('abcdefghijkl…')
  })
})
