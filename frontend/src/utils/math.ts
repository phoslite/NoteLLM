/** 数学公式定界符归一化：把 LLM 常见的非标准写法转换为 $...$ / $$...$$。 */

/** 块级裸方括号 [ ... ]（独占一行且内容含 LaTeX 命令）→ $$...$$。 */
export function normalizeBlockBrackets(src: string): string {
  return src.replace(/^\s*\[\s*\n?([\s\S]*?)\s*\]\s*$/gm, (m: string, inner: string) =>
    inner.includes('\\') ? '$$' + inner.trim() + '$$' : m,
  )
}

/** 标准转义定界符 \(...\) / \[...\] → $...$ / $$...$$。 */
export function normalizeDelimiters(src: string): string {
  return src
    .replace(/\\\[([\s\S]*?)\\\]/g, (_m: string, inner: string) => '$$' + inner.trim() + '$$')
    .replace(/\\\(([^()\n]*)\\\)/g, (_m: string, inner: string) => '$' + inner.trim() + '$')
}

/** 行内裸圆括号 ( ... )（内容含 LaTeX 命令，支持嵌套）→ $...$；跳过已用 $ 定界的公式。 */
export function normalizeInlineParens(src: string): string {
  let out = ''
  let i = 0
  while (i < src.length) {
    const ch = src[i]
    if (ch === '$') {
      // 跳过 $...$ / $$...$$ 定界区域，避免对已转换的公式二次包裹
      if (src[i + 1] === '$') {
        const close = src.indexOf('$$', i + 2)
        if (close === -1) {
          out += src.slice(i)
          break
        }
        out += src.slice(i, close + 2)
        i = close + 2
      } else {
        const next = src.indexOf('$', i + 1)
        if (next === -1) {
          out += src.slice(i)
          break
        }
        out += src.slice(i, next + 1)
        i = next + 1
      }
      continue
    }
    if (ch === '(') {
      let depth = 0
      let j = i
      let hasCommand = false
      let ok = true
      for (; j < src.length; j++) {
        const c = src[j]
        if (c === '(') depth++
        else if (c === ')') {
          depth--
          if (depth === 0) break
        } else if (c === '\\') hasCommand = true
        else if (c === '\n') {
          ok = false
          break
        }
      }
      if (ok && j < src.length && depth === 0 && hasCommand) {
        out += '$' + src.slice(i + 1, j) + '$'
        i = j + 1
        continue
      }
    }
    out += ch
    i++
  }
  return out
}

/** 组合归一化（代码围栏内不做转换）。 */
export function normalizeMath(src: string): string {
  const fences = src.match(/```[\s\S]*?```/g) ?? []
  const parts = src.split(/```[\s\S]*?```/g)
  let out = ''
  for (let i = 0; i < parts.length; i++) {
    out += normalizeInlineParens(normalizeDelimiters(normalizeBlockBrackets(parts[i])))
    if (i < fences.length) out += fences[i]
  }
  return out
}
