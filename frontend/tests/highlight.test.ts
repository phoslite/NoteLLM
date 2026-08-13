import { describe, expect, it } from 'vitest'
import { findQuoteRange, normalizeHlText, paraTextsFingerprint, type HlTextNode } from '../src/utils/highlight'

/** 构造文本节点描述（node 占位；单测只验证纯匹配逻辑）。 */
function n(text: string, opts: { katex?: boolean; mark?: boolean } = {}): HlTextNode {
  return {
    node: null as unknown as Text,
    text,
    matchable: !opts.katex && !opts.mark,
    inMark: !!opts.mark,
  }
}

describe('normalizeHlText（四轮 #1：换行/连续空格归一化）', () => {
  it('折叠换行与连续空格为单个空格', () => {
    expect(normalizeHlText('第一行\n第二行')).toBe('第一行 第二行')
    expect(normalizeHlText('a   b\t\tc')).toBe('a b c')
    expect(normalizeHlText('  前后空白  ')).toBe('前后空白')
  })
})

describe('findQuoteRange（四轮 #1：划词高亮归一化匹配）', () => {
  it('跨文本节点命中', () => {
    const nodes = [n('证明：'), n('公式与'), n('结论')]
    const hits = findQuoteRange(nodes, '公式与结论')
    expect(hits).not.toBeNull()
    expect(hits!.map((h) => [h.nodeIndex, nodes[h.nodeIndex].text.slice(h.start, h.end)])).toEqual([
      [1, '公式与'],
      [2, '结论'],
    ])
  })

  it('选区文本含换行/多空格时仍可命中', () => {
    const nodes = [n('第一行\n第二行'), n('  abc   def  ')]
    const hits = findQuoteRange(nodes, '第一行 第二行 abc def')
    expect(hits).not.toBeNull()
    expect(hits!.map((h) => nodes[h.nodeIndex].text.slice(h.start, h.end))).toEqual(['第一行\n第二行', '  abc   def'])
  })

  it('命中区间落在单节点内部时按原始下标切片', () => {
    const nodes = [n('前缀 12345 后缀')]
    const hits = findQuoteRange(nodes, '12345')
    expect(hits).toEqual([{ nodeIndex: 0, start: 3, end: 8 }])
  })

  it('剥离 KaTeX 数学文本：公式节点不参与匹配', () => {
    const nodes = [n('证明：'), n('F(s)=\int', { katex: true }), n('收敛')]
    // 含公式的选区文本无法在剥离后的 DOM 文本中命中（回退整段高亮由调用方处理）
    expect(findQuoteRange(nodes, '证明：F(s)=\int收敛')).toBeNull()
    // 公式旁纯文本仍可命中（公式自动跳过、不影响其他高亮）
    const hits = findQuoteRange(nodes, '证明：收敛')
    expect(hits).not.toBeNull()
    expect(hits!.map((h) => nodes[h.nodeIndex].text.slice(h.start, h.end))).toEqual(['证明：', '收敛'])
  })

  it('跳过已有 mark 内部文本（m4：防嵌套 mark）', () => {
    const nodes = [n('长引文abc'), n('短引文', { mark: true }), n('尾部')]
    expect(findQuoteRange(nodes, '短引文')).toBeNull()
    // 放宽到「含 mark 内节点」后命中 → 调用方据此判定「仅命中旧 mark 内部」而静默跳过
    const loosened = nodes.map((x) => ({ ...x, matchable: x.matchable || x.inMark }))
    expect(findQuoteRange(loosened, '短引文')).not.toBeNull()
  })

  it('未命中返回 null；空引用返回 null', () => {
    expect(findQuoteRange([n('abc')], 'xyz')).toBeNull()
    expect(findQuoteRange([n('abc')], '  ')).toBeNull()
    expect(findQuoteRange([n('abc')], '')).toBeNull()
  })

  it('跨节点空白折叠：节点边界处的空格可参与匹配', () => {
    const nodes = [n('abc '), n('def')]
    const hits = findQuoteRange(nodes, 'abc def')
    expect(hits).not.toBeNull()
    expect(hits!.map((h) => nodes[h.nodeIndex].text.slice(h.start, h.end))).toEqual(['abc ', 'def'])
  })
})

describe('paraTextsFingerprint（P2-3：段落文本内容指纹缓存键）', () => {
  it('相同内容指纹一致；内容变化指纹不同', () => {
    const a = ['第一段', '第二段']
    expect(paraTextsFingerprint(a)).toBe(paraTextsFingerprint(['第一段', '第二段']))
    expect(paraTextsFingerprint(a)).not.toBe(paraTextsFingerprint(['第一段', '第二段改']))
  })

  it('段间分隔参与哈希：["ab","c"] 与 ["a","bc"] 指纹不同', () => {
    expect(paraTextsFingerprint(['ab', 'c'])).not.toBe(paraTextsFingerprint(['a', 'bc']))
  })

  it('空列表与单段指纹稳定', () => {
    expect(paraTextsFingerprint([])).toBe(paraTextsFingerprint([]))
    expect(paraTextsFingerprint([''])).toBe(paraTextsFingerprint(['']))
  })
})