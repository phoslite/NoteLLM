/** 章节正文处理工具（纯函数）。 */

/** 按空行把正文切成渲染块；保持 ``` 代码块不被截断。 */
export function splitBlocks(source: string): string[] {
  const blocksOut: string[] = []
  for (const raw of source.split(/\n\s*\n/)) {
    const trimmed = raw.trim()
    if (!trimmed) continue
    const last = blocksOut[blocksOut.length - 1]
    if (last && last.startsWith('```') && !last.trimEnd().endsWith('```')) {
      blocksOut[blocksOut.length - 1] = last + '\n\n' + trimmed
    } else {
      blocksOut.push(trimmed)
    }
  }
  return blocksOut
}
