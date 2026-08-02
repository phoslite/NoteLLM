/// <reference types="vite/client" />

declare module 'markdown-it' {
  interface MarkdownItOptions {
    html?: boolean
    linkify?: boolean
    breaks?: boolean
  }
  class MarkdownIt {
    constructor(options?: MarkdownItOptions)
    render(src: string): string
    renderInline(src: string): string
  }
  export default MarkdownIt
}

declare module 'katex/dist/contrib/auto-render.mjs' {
  interface AutoRenderOptions {
    delimiters?: Array<{ left: string; right: string; display: boolean }>
    throwOnError?: boolean
  }
  export default function renderMathInElement(elem: HTMLElement, options?: AutoRenderOptions): void
}