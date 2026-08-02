import { describe, expect, it } from 'vitest'
import { normalizeBlockBrackets, normalizeDelimiters, normalizeInlineParens, normalizeMath } from '../src/utils/math'

describe('normalizeInlineParens', () => {
  it('裸圆括号含 LaTeX 命令 → 行内公式 $...$（支持嵌套）', () => {
    expect(normalizeInlineParens('其端点集为 (\\operatorname{ext}(K))。')).toBe('其端点集为 $\\operatorname{ext}(K)$。')
    expect(normalizeInlineParens('(\\overline{\\operatorname{conv}}(\\operatorname{ext}(K)))')).toBe(
      '$\\overline{\\operatorname{conv}}(\\operatorname{ext}(K))$',
    )
  })

  it('无 LaTeX 命令的圆括号保持文本', () => {
    expect(normalizeInlineParens('（见上文） (K) 普通文本')).toBe('（见上文） (K) 普通文本')
  })

  it('跳过已用 $ 定界的公式，避免二次包裹', () => {
    expect(normalizeInlineParens('公式 $\\operatorname{ext}(K)$ 之后')).toBe('公式 $\\operatorname{ext}(K)$ 之后')
  })
})

describe('normalizeBlockBrackets', () => {
  it('独占一行且含 LaTeX 命令的 [ ... ] → 块级公式 $$...$$', () => {
    const input = '定理说：\n[\nK = \\overline{\\operatorname{conv}}(\\operatorname{ext}(K)).\n]'
    expect(normalizeBlockBrackets(input)).toBe(
      '定理说：\n$$K = \\overline{\\operatorname{conv}}(\\operatorname{ext}(K)).$$',
    )
  })

  it('不含 LaTeX 命令的方括号保持文本', () => {
    expect(normalizeBlockBrackets('- [ ] 任务\n[0,1] 区间')).toBe('- [ ] 任务\n[0,1] 区间')
  })
})

describe('normalizeDelimiters', () => {
  it('\\(...\\) / \\[...\\] → $...$ / $$...$$', () => {
    expect(normalizeDelimiters('\\(x_1\\) 与 \\[y = x^2\\]')).toBe('$x_1$ 与 $$y = x^2$$')
  })
})

describe('normalizeMath', () => {
  it('组合处理用户样例（行内 + 块级裸定界符）', () => {
    const input = '记集合为 (K)，其端点集为 (\\operatorname{ext}(K))。定理说：\n[\nK = \\overline{\\operatorname{conv}}(\\operatorname{ext}(K)).\n]'
    const expected =
      '记集合为 (K)，其端点集为 $\\operatorname{ext}(K)$。定理说：\n$$K = \\overline{\\operatorname{conv}}(\\operatorname{ext}(K)).$$'
    expect(normalizeMath(input)).toBe(expected)
  })

  it('代码围栏内不做转换', () => {
    const input = '```\n[a \\\\b]\n```'
    expect(normalizeMath(input)).toBe(input)
  })
})
