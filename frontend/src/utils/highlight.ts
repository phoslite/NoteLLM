/** 正文高亮（笔记 mark）匹配工具（E2E 四轮 #1 修复）。
 *
 * 划词高亮原先用选区文本对 DOM textContent 做精确 indexOf：选区文本含换行/多空格、
 * KaTeX 数学节点（.katex 内同时存在 MathML 与 HTML 两份文本）时无法命中，
 * 导致含公式段落整段无高亮且无提示。
 *
 * 新策略：
 * 1. 两侧都做空白归一化（换行/连续空格折叠为单个空格）后再匹配；
 * 2. 匹配与包裹时跳过 KaTeX 公式节点与已有 .note-hl 内的文本节点
 *    （公式自动跳过、防嵌套 mark，行为与手册「公式自动跳过、不影响其他高亮」一致）；
 * 3. 仍无法命中时由调用方回退「整段高亮」（跳过公式与已有 mark）。
 */

export interface HlTextNode {
  /** 文本节点（DOM 环境为真实 Text；单测可用占位对象）。 */
  node: Text
  /** 节点原始文本（textContent）。 */
  text: string
  /** 参与匹配与包裹：.katex 公式节点与 .note-hl 内的文本节点为 false。 */
  matchable: boolean
  /** 位于已有 mark（.note-hl）内（仅用于区分「命中旧 mark 内部」与「公式段落回退」）。 */
  inMark: boolean
}

export interface HlRange {
  /** 对应 nodes 数组下标。 */
  nodeIndex: number
  /** 包裹起点（该节点原始文本下标）。 */
  start: number
  /** 包裹终点（该节点原始文本下标，开区间）。 */
  end: number
}

/** 空白归一化：任意空白（含换行/制表/连续空格）折叠为单个空格并去首尾。 */
export function normalizeHlText(s: string): string {
  return s.replace(/\s+/g, ' ').trim()
}

/**
 * 在文本节点序列中查找 quote 的归一化区间。
 * - 两侧空白归一化后匹配（选区文本含换行/多空格仍可命中）；
 * - 跳过 matchable=false 的节点（KaTeX 公式、已有 mark 内部）；
 * - 命中时返回覆盖区间的节点切片（start/end 为原始文本下标，支持跨节点）。
 * - 未命中返回 null。
 */
export function findQuoteRange(nodes: HlTextNode[], quote: string): HlRange[] | null {
  const q = normalizeHlText(quote)
  if (!q) return null
  // 全局归一化拼接（跨节点空白折叠为单个空格）+ 每节点「归一化下标 → 原始下标」映射
  const maps: number[][] = []
  const normLens: number[] = []
  let full = ''
  let lastChar = ''
  for (let i = 0; i < nodes.length; i++) {
    const map: number[] = []
    maps.push(map)
    if (!nodes[i].matchable) {
      normLens.push(0)
      continue
    }
    const t = nodes[i].text
    let j = 0
    while (j < t.length) {
      const ch = t[j]
      if (/\s/.test(ch)) {
        if (lastChar && lastChar !== ' ') {
          full += ' '
          map.push(j)
          lastChar = ' '
        }
        j++
        continue
      }
      full += ch
      map.push(j)
      lastChar = ch
      j++
    }
    normLens.push(map.length)
  }
  const idx = full.indexOf(q)
  if (idx < 0) return null
  const end = idx + q.length
  const hits: HlRange[] = []
  let acc = 0
  for (let i = 0; i < nodes.length; i++) {
    if (!nodes[i].matchable) continue
    const nodeStart = acc
    const nodeEnd = acc + normLens[i]
    acc = nodeEnd
    const ovStart = Math.max(idx, nodeStart)
    const ovEnd = Math.min(end, nodeEnd)
    if (ovStart >= ovEnd) continue
    hits.push({
      nodeIndex: i,
      start: maps[i][ovStart - nodeStart],
      end: maps[i][ovEnd - nodeStart - 1] + 1,
    })
  }
  return hits.length ? hits : null
}

/** 段落文本列表的轻量内容指纹（djb2，P2-3）：参与 buildParaTexts 缓存键，同章内容变化时键必然失配。 */
export function paraTextsFingerprint(texts: string[]): string {
  let hash = 5381
  for (const t of texts) {
    for (let i = 0; i < t.length; i++) {
      hash = ((hash << 5) + hash + t.charCodeAt(i)) >>> 0
    }
    // 段间分隔符（0x2c = ','），避免 ['ab','c'] 与 ['a','bc'] 指纹相同
    hash = ((hash << 5) + hash + 0x2c) >>> 0
  }
  return hash.toString(36)
}
