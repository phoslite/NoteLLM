/** 搜索片段关键词高亮（四轮 m5 修复）。
 *
 * 原实现先 escapeHtml 再按词正则包裹：查询含 & < > " 时实体化（&amp; 等）后词元无法命中。
 * 新实现：转义前定位命中区间、转义后按偏移插入 <mark>（XSS 面不变：$1 仍为转义后文本）。
 */
import { escapeHtml } from './graphLabel'

export interface SnippetHighlightRange {
  start: number
  end: number
}

/** 在原始文本上定位查询词命中区间（大小写不敏感；& < > " 等字符按原文匹配）。 */
export function findSnippetRanges(text: string, query: string): SnippetHighlightRange[] {
  const terms = query.trim().split(/\s+/).filter(Boolean)
  if (!terms.length) return []
  const pattern = terms.map((t) => t.replace(/[^\w\u4e00-\u9fa5]/g, (m) => '\\' + m)).join('|')
  let re: RegExp
  try {
    re = new RegExp('(' + pattern + ')', 'gi')
  } catch {
    return []
  }
  const ranges: SnippetHighlightRange[] = []
  let m: RegExpExecArray | null
  while ((m = re.exec(text))) {
    if (!m[0]) {
      // 防零宽匹配死循环
      re.lastIndex += 1
      continue
    }
    ranges.push({ start: m.index, end: m.index + m[0].length })
  }
  return ranges
}

/** 转义前定位命中区间、转义后按偏移插入 <mark>；无命中返回纯转义文本。 */
export function highlightSnippet(text: string, query: string): string {
  const ranges = findSnippetRanges(text, query)
  if (!ranges.length) return escapeHtml(text)
  const escaped = escapeHtml(text)
  // 原始字符下标 → 转义后下标映射（逐字符转义长度累加）
  const map: number[] = []
  let outLen = 0
  for (const ch of text) {
    map.push(outLen)
    outLen += escapeHtml(ch).length
  }
  let out = ''
  let last = 0
  for (const r of ranges) {
    const start = map[r.start]
    const end = r.end > 0 ? map[r.end - 1] + escapeHtml(text[r.end - 1]).length : start
    if (end <= start) continue
    out += escaped.slice(last, start) + '<mark>' + escaped.slice(start, end) + '</mark>'
    last = end
  }
  return out + escaped.slice(last)
}