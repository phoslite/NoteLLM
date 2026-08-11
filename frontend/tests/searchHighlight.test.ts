import { describe, expect, it } from 'vitest'
import { findSnippetRanges, highlightSnippet } from '../src/utils/searchHighlight'

/** m5 回归测试（四轮）：highlightSnippet 在 escapeHtml 前定位命中区间，实体化字符（& < > "）仍可命中。 */
describe('findSnippetRanges', () => {
  it('普通词命中返回原始偏移', () => {
    expect(findSnippetRanges('中文测试片段', '测试')).toEqual([{ start: 2, end: 4 }])
  })

  it('& < 等实体化字符按原文匹配', () => {
    expect(findSnippetRanges('C++ & C <模板>', '& <')).toEqual([
      { start: 4, end: 5 },
      { start: 8, end: 9 },
    ])
  })

  it('大小写不敏感', () => {
    expect(findSnippetRanges('HelloWorld', 'hello')).toEqual([{ start: 0, end: 5 }])
  })

  it('无命中/空查询返回空数组', () => {
    expect(findSnippetRanges('abc', 'xyz')).toEqual([])
    expect(findSnippetRanges('abc', '  ')).toEqual([])
  })
})

describe('highlightSnippet', () => {
  it('& 与 < 关键词实体化后仍插入 mark', () => {
    const html = highlightSnippet('C++ & C <模板> 指针', '& <')
    expect(html).toBe('C++ <mark>&amp;</mark> C <mark>&lt;</mark>模板&gt; 指针')
    expect(html).not.toContain('<mark>&lt;/mark>')
  })

  it('普通词包裹 mark 且其余内容转义', () => {
    expect(highlightSnippet('含矩阵与向量', '矩阵')).toBe('含<mark>矩阵</mark>与向量')
    expect(highlightSnippet('<b>bold</b>', 'bold')).toBe('&lt;b&gt;<mark>bold</mark>&lt;/b&gt;')
  })

  it('无命中时只转义不包裹', () => {
    expect(highlightSnippet('<script>x</script>', 'nope')).toBe('&lt;script&gt;x&lt;/script&gt;')
  })

  it('多词命中互不干扰', () => {
    expect(highlightSnippet('alpha beta gamma', 'alpha gamma')).toBe('<mark>alpha</mark> beta <mark>gamma</mark>')
  })
})