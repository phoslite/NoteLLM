/**
 * 图谱节点/边标签渲染工具：
 * - 节点名中的 LaTeX 公式（$...$ / $$...$$ / \(...\) / \[...\] / 裸 \command 段）
 *   用 MathJax tex2svg 渲染为 SVG data URL，嵌入 ECharts 富文本图片片段
 *   （KaTeX 不提供 SVG 输出，MathJax 在 Node/浏览器均可用同一套 API）；
 * - Markdown 标记（**加粗**、`代码`、链接等）清洗为纯文本；
 * - tooltip 用 markdown-it + KaTeX（HTML 输出）生成 HTML。
 */
import type MarkdownIt from 'markdown-it'
import type DOMPurify from 'dompurify'
import { normalizeMath } from './math'

export const LABEL_FONT_SIZE = 10
/** MathJax TeX 字体的 x-height 比例（font.params.n），1ex = 0.442em。 */
const MATHJAX_EX_RATIO = 0.442
/** 文本段最大显示字符数（中英文混排按字符计）。 */
const MAX_TEXT_CHARS = 12
/** 单个节点标签允许的最大公式个数（避免一个名字全是公式导致过宽）。 */
const MAX_FORMULAS = 2

type KatexApi = typeof import('katex')

let katexApi: KatexApi | null = null
let katexReady: Promise<void> | null = null

/** 按需加载 KaTeX（tooltip 公式 HTML 用，只加载一次）。 */
export function ensureKatex(): Promise<void> {
  if (!katexReady) {
    katexReady = import('katex').then((m) => {
      katexApi = m as KatexApi
    })
  }
  return katexReady
}

interface MathJaxApi {
  convert: (latex: string) => string
}

let mathJaxApi: MathJaxApi | null = null
let mathJaxReady: Promise<void> | null = null

/** 按需加载 MathJax tex2svg（公式 → SVG 字符串，只加载一次）。 */
export function ensureMathJax(): Promise<void> {
  if (!mathJaxReady) {
    mathJaxReady = (async () => {
      try {
        const { mathjax } = await import('mathjax-full/js/mathjax.js')
        const { TeX } = await import('mathjax-full/js/input/tex.js')
        const { SVG } = await import('mathjax-full/js/output/svg.js')
        const { liteAdaptor } = await import('mathjax-full/js/adaptors/liteAdaptor.js')
        const { RegisterHTMLHandler } = await import('mathjax-full/js/handlers/html.js')
        const { AllPackages } = await import('mathjax-full/js/input/tex/AllPackages.js')
        const adaptor = liteAdaptor()
        RegisterHTMLHandler(adaptor)
        const tex = new TeX({ packages: AllPackages })
        const svgOutput = new SVG({ fontCache: 'none' })
        const doc = mathjax.document('', { InputJax: tex, OutputJax: svgOutput })
        mathJaxApi = {
          convert: (latex: string) => {
            const node = doc.convert(latex, { display: false })
            const outer = adaptor.outerHTML(node)
            const svgMatch = outer.match(/<svg[\s\S]*?<\/svg>/)
            return svgMatch ? svgMatch[0] : ''
          },
        }
      } catch {
        mathJaxApi = null
      }
    })()
  }
  return mathJaxReady
}

let mdApi: MarkdownIt | null = null
let purifyApi: typeof DOMPurify | null = null
let mdReady: Promise<void> | null = null

/** 预加载 markdown-it + DOMPurify（tooltip 渲染用，同步 formatter 依赖就绪）。 */
export function ensureTooltipReady(): Promise<void> {
  if (!mdReady) {
    mdReady = Promise.all([
      import('markdown-it')
        .then((m) => {
          const Ctor = (m as { default?: typeof MarkdownIt }).default ?? (m as unknown as typeof MarkdownIt)
          mdApi = new Ctor({ html: false, linkify: true, breaks: true })
        })
        .catch(() => {
          mdApi = null
        }),
      import('dompurify')
        .then((m) => {
          purifyApi = (m as { default?: typeof DOMPurify }).default ?? (m as unknown as typeof DOMPurify)
        })
        .catch(() => {
          purifyApi = null
        }),
    ]).then(() => undefined)
  }
  return mdReady
}

/** 一次性加载标签/tooltip 所需全部依赖。 */
export async function ensureGraphLabelReady(): Promise<void> {
  await Promise.all([ensureMathJax(), ensureKatex(), ensureTooltipReady()])
}

const formulaCache = new Map<string, { url: string; width: number; height: number }>()

export interface FormulaImage {
  url: string
  width: number
  height: number
}

/**
 * LaTeX → SVG data URL + 显示尺寸（px）。
 * 失败（MathJax 抛错或未就绪）返回 null，调用方按纯文本展示。
 */
export function formulaToImage(latex: string, fontSize = LABEL_FONT_SIZE): FormulaImage | null {
  if (!mathJaxApi) return null
  const key = `${fontSize}|${latex}`
  const hit = formulaCache.get(key)
  if (hit) return hit
  let svg = ''
  try {
    svg = mathJaxApi.convert(latex)
  } catch {
    return null
  }
  if (!svg) return null
  // MathJax 对非法公式不抛错，而是输出 data-mjx-error 错误 SVG，此时回退纯文本
  if (svg.includes('data-mjx-error')) return null
  const wm = svg.match(/width="([\d.]+)ex"/)
  const hm = svg.match(/height="([\d.]+)ex"/)
  if (!wm || !hm) return null
  const width = Math.ceil(parseFloat(wm[1]) * fontSize * MATHJAX_EX_RATIO)
  const height = Math.ceil(parseFloat(hm[1]) * fontSize * MATHJAX_EX_RATIO)
  if (!width || !height || width > 600 || height > 120) return null
  // 去掉 vertical-align 等对 <img> 无意义的行内样式，避免影响图片定位
  const cleanSvg = svg.replace(/\sstyle="[^"]*"/, '')
  const url = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(cleanSvg)}`
  const out = { url, width, height }
  formulaCache.set(key, out)
  return out
}

/** Markdown 标记 → 纯文本（保留公式占位符不动）。 */
export function stripMarkdown(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, '')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/__([^_]+)__/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/~~([^~]+)~~/g, '$1')
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/^\s{0,3}(#{1,6})\s*/gm, '')
    .replace(/^\s{0,3}>\s?/gm, '')
    .replace(/^\s*[-*+]\s+/gm, '')
    .replace(/^\s*\d+[.、]\s*/gm, '')
    .replace(/^\s*[-*_]{3,}\s*$/gm, '')
    .replace(/[ \t]+/g, ' ')
    .replace(/\n+/g, ' ')
    .trim()
}

/** 行内公式定界符（含 $$、$、\[..\]、\(..\)）。 */
const INLINE_MATH_RE = /\$\$([\s\S]*?)\$\$|\$([^$\n]+?)\$|\\\[([\s\S]*?)\\\]|\\\(([^()\n]*)\\\)/g

export type LabelSeg = { type: 'text'; text: string } | { type: 'formula'; formula: string; image: FormulaImage }

/**
 * 把节点名切分为「文本段 + 公式段」。
 * 公式定界由 normalizeMath 先归一化；裸 \command 片段（无 $ 定界）也尝试按公式渲染。
 */
export function splitLabelSegments(raw: string, fontSize = LABEL_FONT_SIZE): LabelSeg[] {
  const src = normalizeMath(raw ?? '')
  const segs: LabelSeg[] = []
  let last = 0
  let formulaCount = 0
  const tryFormula = (latex: string): LabelSeg | null => {
    if (formulaCount >= MAX_FORMULAS) return null
    const image = formulaToImage(latex, fontSize)
    if (!image) return null
    formulaCount++
    return { type: 'formula', formula: latex, image }
  }
  for (const m of src.matchAll(INLINE_MATH_RE)) {
    const idx = m.index ?? 0
    if (idx > last) segs.push({ type: 'text', text: stripMarkdown(src.slice(last, idx)) })
    const latex = (m[1] ?? m[2] ?? m[3] ?? m[4] ?? '').trim()
    if (latex) {
      const f = tryFormula(latex)
      segs.push(f ?? { type: 'text', text: stripMarkdown(latex) })
    }
    last = idx + m[0].length
  }
  if (last < src.length) segs.push({ type: 'text', text: stripMarkdown(src.slice(last)) })
  // 裸 LaTeX 段：以 \ 开头且无中文，尝试整体渲染为公式
  return segs.flatMap((s) => {
    if (s.type === 'text' && s.text.startsWith('\\') && !/[\u4e00-\u9fff]/.test(s.text) && s.text.length <= 80) {
      const f = tryFormula(s.text)
      if (f) return [f]
    }
    return [s]
  })
}

/** 截断文本段（保留开头，尾部加 …）。 */
export function truncateLabelText(text: string, max = MAX_TEXT_CHARS): string {
  const t = text.trim()
  if (!t) return ''
  return t.length > max ? `${t.slice(0, max)}…` : t
}

/**
 * 标签富文本：普通文本 + 公式图片片段。
 * 返回 ECharts 可用的「字符串 token + rich 样式表」（graph 系列 label formatter
 * 不支持返回对象，返回对象会被 zrender 字符串化成 "[object Object]"）。
 * 文本段直接拼接为普通字符（沿用 label 默认样式），公式段用 {fN| } token 内嵌图片。
 */
export function labelRichFormatter(
  raw: string,
  fontSize = LABEL_FONT_SIZE,
  maxChars = MAX_TEXT_CHARS,
): {
  formatter: string
  rich: Record<string, { backgroundColor: { image: string }; width: number; height: number }>
} {
  const segs = splitLabelSegments(raw, fontSize)
  const rich: Record<string, { backgroundColor: { image: string }; width: number; height: number }> = {}
  const parts: string[] = []
  let imgIdx = 0
  let textBuf = ''
  const flushText = () => {
    const t = truncateLabelText(textBuf, maxChars)
    if (t) parts.push(t)
    textBuf = ''
  }
  for (const s of segs) {
    if (s.type === 'formula') {
      flushText()
      const name = `f${imgIdx++}`
      rich[name] = { backgroundColor: { image: s.image.url }, width: s.image.width, height: s.image.height }
      parts.push(`{${name}| }`)
    } else {
      textBuf += s.text
    }
  }
  flushText()
  if (!parts.length) parts.push('…')
  return { formatter: parts.join(''), rich }
}

export const escapeHtml = (s: string) =>
  s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')

/** tooltip/弹窗用：Markdown + LaTeX → 消毒后的 HTML 字符串（依赖需先 ensureGraphLabelReady）。 */
export function renderTooltipHtml(src: string, inline = false): string {
  const raw = src ?? ''
  // 公式保护：占位符避免 markdown-it 破坏数学内容
  const stored = new Map<string, string>()
  let id = 0
  const protect = (s: string) => {
    const token = `\uE000${id++}\uE001`
    stored.set(token, s)
    return token
  }
  let seg = normalizeMath(raw)
  seg = seg.replace(/\$\$([\s\S]*?)\$\$/g, (_m, inner: string) => protect('$$' + inner.trim() + '$$'))
  seg = seg.replace(/\\\[([\s\S]*?)\\\]/g, (_m, inner: string) => protect('\\[' + inner.trim() + '\\]'))
  seg = seg.replace(/(^|[^$\n\\])\$([^\s$][^$\n]*?[^\s$])\$([^$\n\\]|$)/g, (_m: string, pre: string, inner: string, post: string) => pre + protect('$' + inner + '$') + post)
  seg = seg.replace(/\\\(([^()\n]*)\\\)/g, (_m: string, inner: string) => protect('\\(' + inner + '\\)'))
  if (!mdApi) return escapeHtml(raw)
  const rendered = inline ? mdApi.renderInline(seg) : mdApi.render(seg)
  const html = rendered.replace(/\uE000(\d+)\uE001/g, (_m, n: string) => {
    const formula = stored.get(`\uE000${n}\uE001`) ?? ''
    if (katexApi) {
      try {
        const display = formula.startsWith('$$')
        const latex = formula.replace(/^\$\$?/, '').replace(/\$\$?$/, '')
        return katexApi.renderToString(latex, { output: 'html', throwOnError: true, displayMode: display })
      } catch {
        /* 渲染失败按纯文本 */
      }
    }
    return escapeHtml(formula)
  })
  return purifyApi ? purifyApi.sanitize(html) : html
}
