/** 阅读进度换算工具：进度值/已读章节数 → 整数百分比。 */

/** 0..1 的进度值 → 整数百分比（如 0.432 → 43）。 */
export function percentOf(progress: number | null | undefined): number {
  return Math.round((progress ?? 0) * 100)
}

/** 按「已读章节数 / 总章节数」计算整书进度百分比（章节式阅读）。 */
export function chapterPercent(
  readChapters: number | null | undefined,
  totalChapters: number | null | undefined,
): number {
  return totalChapters ? Math.round(((readChapters ?? 0) / totalChapters) * 100) : 0
}
