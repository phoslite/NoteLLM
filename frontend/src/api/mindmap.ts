import type { MindMapResult } from '@/types'
import { post } from './client'

/** 生成章节/选中段落的层级化脑图（ECharts 树数据 + Markdown 大纲）。 */
export function generateMindmap(
  bookId: number,
  body: { chapter_id?: number | null; selection?: string; focus?: string },
) {
  return post<MindMapResult>(`/books/${bookId}/mindmap`, body)
}
