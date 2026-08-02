import { describe, expect, it } from 'vitest'
import { toPlainDisplayText } from '../src/utils/text'

describe('toPlainDisplayText', () => {
  it('去除 $ 定界符保留内文', () => {
    expect(toPlainDisplayText('端点集为 $\\operatorname{ext}(K)$')).toBe('端点集为 ext(K)')
    expect(toPlainDisplayText('对偶空间 $V^*$ 与 $(K)$')).toBe('对偶空间 V^ 与 (K)')
  })

  it('去除 LaTeX 命令与花括号', () => {
    expect(toPlainDisplayText('(\\overline{\\operatorname{conv}}(K))')).toBe('(conv(K))')
    expect(toPlainDisplayText('$\\mathbb{R}^n$ 空间')).toBe('R^n 空间')
  })

  it('去除 Markdown 记号', () => {
    expect(toPlainDisplayText('**重要定理**：`code` 与 # 标题')).toBe('重要定理：code 与  标题')
    expect(toPlainDisplayText('X_1 下标')).toBe('X1 下标')
  })

  it('空值安全', () => {
    expect(toPlainDisplayText('')).toBe('')
  })
})
