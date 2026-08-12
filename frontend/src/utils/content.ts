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

/** 模块级正文解析缓存（性能优化第二梯队）：同一章节正文只切一次，LRU 上限 30 条。 */
const splitCache = new Map<string, string[]>()
const SPLIT_CACHE_MAX = 30

function quickHash(source: string): string {
  let h = 0
  for (let i = 0; i < source.length; i++) {
    h = (h * 31 + source.charCodeAt(i)) | 0
  }
  return (h >>> 0).toString(36)
}

/** 按 (长度+首 80 字符+hash) 缓存 splitBlocks 结果，章节切换/回退时避免重复切分大文本。
 *  P3-2：真 LRU——命中时刷新为最近使用，超限删除最久未用项。 */
export function cachedSplitBlocks(source: string): string[] {
  const key = `${source.length}:${source.slice(0, 80)}:${quickHash(source)}`
  const hit = splitCache.get(key)
  if (hit) {
    splitCache.delete(key)
    splitCache.set(key, hit) // 刷新访问序（Map 迭代序 = 最近使用序）
    return hit
  }
  const blocks = splitBlocks(source)
  splitCache.set(key, blocks)
  while (splitCache.size > SPLIT_CACHE_MAX) {
    const oldest = splitCache.keys().next().value
    if (oldest === undefined) break
    splitCache.delete(oldest)
  }
  return blocks
}
