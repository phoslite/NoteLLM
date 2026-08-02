/** 文本清洗工具（纯函数）。 */

/** 脑图节点显示文本：去除 $...$ 定界、LaTeX 命令与 Markdown 记号，保留可读内文。 */
export function toPlainDisplayText(text: string): string {
  return (text ?? '')
    .replace(/\$([^$]*)\$/g, (_, inner: string) => inner) // 去 $ 定界符，保留内文
    .replace(/\\\(|\\\)/g, '') // 去转义定界符
    .replace(/\\[a-zA-Z]+/g, '') // 去 LaTeX 命令名（\operatorname → 空）
    .replace(/[{}\\]/g, '') // 去花括号与残留反斜杠
    .replace(/[*_`#]/g, '') // 去 Markdown 记号
    .replace(/^\s+|\s+$/g, '')
}
