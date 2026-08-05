<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import 'katex/dist/katex.min.css'
import { normalizeMath } from '@/utils/math'

/** Markdown/LaTeX 统一渲染（技术栈规范 §4.6）：markdown-it + KaTeX auto-render + DOMPurify 消毒。 */
const props = defineProps<{ source: string; inline?: boolean }>()

const el = ref<HTMLElement | null>(null)
const md = new MarkdownIt({ html: false, linkify: true, breaks: true })

/**
 * 渲染前保护数学公式：把 $...$ / $$...$$ 整体替换为占位符，
 * 避免 markdown-it 把数学内容里的 * _ < > 等当成 Markdown 语法（如 $V^*$ 被解析成 <em>），
 * 渲染后再把占位符还原为公式文本（HTML 转义），交给 KaTeX auto-render 处理。
 */
/**
 * 还原 LLM 常见的引号写法：\" → "，并把 **"X"** 调整为 "**X**"（引号移到加粗标记外侧）。
 * markdown-it 按 CommonMark 规则：** 紧贴标点（如 " '）后接非标点时无法开闭强调，
 * 例如 **"算法先于理论"**的历史 不会渲染加粗；调整后保留引号原意且加粗生效。
 */
function normalizeQuotes(src: string): string {
  return src
    .replace(/\\"/g, '"')
    .replace(/(\*{2,})[ \t]*(["'])([^"'\n]*?)\2[ \t]*(\*{2,})/g, '$2$1$3$4$2')
}

function protectMath(src: string): { text: string; restore: (html: string) => string } {
  const stored = new Map<string, string>()
  const fences = src.match(/```[\s\S]*?```/g) ?? []
  const parts = src.split(/```[\s\S]*?```/g)
  let id = 0
  const protect = (raw: string): string => {
    const token = `\uE000${id++}\uE001`
    stored.set(token, raw)
    return token
  }
  let out = ''
  for (let i = 0; i < parts.length; i++) {
    // 先归一化 LLM 输出的非标准公式定界符（裸括号/方括号 → $ 定界符）
    let seg = normalizeMath(parts[i])
    // 块级公式 $$...$$
    seg = seg.replace(/\$\$([\s\S]*?)\$\$/g, (_m, inner: string) => protect('$$' + inner.trim() + '$$'))
    // 转义块级定界符 \[...\]（避免内部 * _ 被 markdown-it 转义）
    seg = seg.replace(/\\\[([\s\S]*?)\\\]/g, (_m, inner: string) => protect('\\[' + inner.trim() + '\\]'))
    // 行内公式 $...$（内容不含 $/换行，前后不是 $ 或 \）
    // 注：允许单字符公式（如 $p$），避免吞掉相邻 `**` 破坏加粗（如 **$p$-积分临界线**）
    seg = seg.replace(
      /(^|[^$\n\\])\$([^\s$](?:[^$\n]*[^\s$])?)\$([^$\n\\]|$)/g,
      (_m: string, pre: string, inner: string, post: string) => pre + protect('$' + inner + '$') + post,
    )
    // 转义行内定界符 \\(...\\)（避免内部 * _ 被 markdown-it 转义）
    seg = seg.replace(/\\\(([^()\n]*)\\\)/g, (_m: string, inner: string) => protect('\\(' + inner + '\\)'))
    out += seg
    if (i < fences.length) out += fences[i]
  }
  const escapeHtml = (s: string) =>
    s
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;')
  return {
    text: out,
    restore: (html: string) =>
      html.replace(/\uE000(\d+)\uE001/g, (_m, n: string) => escapeHtml(stored.get(`\uE000${n}\uE001`) ?? '')),
  }
}

const html = computed(() => {
  const { text, restore } = protectMath(normalizeQuotes(props.source ?? ''))
  const rendered = props.inline ? md.renderInline(text) : md.render(text)
  return DOMPurify.sanitize(restore(rendered))
})

async function renderMath() {
  await nextTick()
  if (!el.value) return
  try {
    const { default: renderMathInElement } = await import('katex/dist/contrib/auto-render.mjs')
    renderMathInElement(el.value, {
      delimiters: [
        { left: '$$', right: '$$', display: true },
        { left: '\\[', right: '\\]', display: true },
        { left: '$', right: '$', display: false },
        { left: '\\(', right: '\\)', display: false },
      ],
      throwOnError: false,
    })
  } catch {
    /* 公式渲染失败不影响正文 */
  }
}

watch(html, renderMath)
onMounted(renderMath)
</script>

<template>
  <div v-if="!inline" ref="el" class="md-render" v-html="html"></div>
  <span v-else ref="el" class="md-render md-render-inline" v-html="html"></span>
</template>

<style scoped>
.md-render { line-height: 1.9; word-break: break-word; }
.md-render-inline { display: inline; line-height: inherit; }
.md-render-inline :deep(.katex) { font-size: 1em; }
.md-render :deep(h1), .md-render :deep(h2), .md-render :deep(h3) { margin: 1.2em 0 0.6em; }
.md-render :deep(p) { margin: 0.6em 0; }
.md-render :deep(ul), .md-render :deep(ol) { padding-left: 1.6em; }
.md-render :deep(blockquote) { margin: 0.8em 0; padding: 0.4em 1em; border-left: 3px solid var(--border-color); color: var(--text-secondary); }
.md-render :deep(code) { background: var(--panel-bg); padding: 0.15em 0.4em; border-radius: 4px; font-size: 0.9em; }
.md-render :deep(pre) { background: var(--panel-bg); padding: 12px; border-radius: 6px; overflow-x: auto; }
.md-render :deep(pre code) { background: none; padding: 0; }
.md-render :deep(table) { border-collapse: collapse; margin: 0.8em 0; }
.md-render :deep(th), .md-render :deep(td) { border: 1px solid var(--border-color); padding: 6px 10px; }
</style>
