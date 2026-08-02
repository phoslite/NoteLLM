import type { GlobalGraph, IntraGraph, KnowledgeAppearsIn } from '@/types'
import { get, post } from './client'

/** 书籍级谱系图：聚类 + 节点 + 关联边。 */
export function getGlobalGraph() {
  return get<GlobalGraph>('/graph/books')
}

/** 书内知识图谱：知识点节点与关系。 */
export function getIntraGraph(bookId: number) {
  return get<IntraGraph>(`/graph/books/${bookId}`)
}

/** 重建全部图谱。 */
export function rebuildGraph() {
  return post<{ books: number; relations: number; knowledge_points: number; linked: number }>('/graph/rebuild')
}

/** 图谱联动沉淀：受影响书籍 RAG/Skill 增量增改（本地存根 + LLM 联动）。 */
export function syncGraphAssets() {
  return post<{ stubs: number; llm_updated: number; domain_terms: number }>('/graph/sync')
}

/** 跨书检索：该知识点还出现在哪些书。 */
export function getKnowledgeAppearsIn(kpId: number) {
  return get<KnowledgeAppearsIn>(`/graph/knowledge/${kpId}/appears-in`)
}

/** 重建单书内部知识图谱。 */
export function rebuildBookGraph(bookId: number) {
  return post<IntraGraph>(`/graph/books/${bookId}/rebuild`)
}

/** 关联人工反馈：确认 / 忽略 / 修改强度。 */
export function relationFeedback(relationId: number, action: string, strength?: number) {
  return post<{ id: number; user_feedback: string; strength: number }>(
    `/graph/relations/${relationId}/feedback`,
    { action, strength },
  )
}