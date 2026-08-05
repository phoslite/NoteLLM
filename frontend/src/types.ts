export interface BookItem {
  id: number
  title: string
  author: string | null
  format: string
  content_hash: string | null
  status: string
  progress: number
  total_chapters: number
  is_scanned: boolean
  page_count: number
  cover_url: string | null
  graph_built: boolean
  tags: string[]
  folder_id: number | null
  position: number
  created_at: string | null
  last_opened_at: string | null
  chapter_count: number
  read_chapters: number
  latest_chapter: { index: number; title: string } | null
}

export interface ChapterItem {
  id: number
  index: number
  title: string
  page_index: number | null
  word_count: number
  read_flag: boolean
}

export interface BookDetail extends BookItem {
  chapters: ChapterItem[]
}

export interface FolderItem {
  id: number
  name: string
  parent_id: number | null
}
export interface RagChunk {
  chapter_index: number
  chapter_title: string
  para_pos: string
  text: string
}

export interface RagContent {
  title?: string
  summary: string
  key_points: string[]
  chunks?: RagChunk[]
}

export interface SkillItem {
  name: string
  applicable?: string
  usage?: string
  sources?: string[]
}

export interface SkillContent {
  name?: string
  domains?: string[]
  skills?: SkillItem[]
  usage?: string
}

export interface AssetEntry<T> {
  content: T
  version: number
  updated_at: string | null
}

export interface BookAssetView {
  rag: AssetEntry<RagContent> | null
  skill: AssetEntry<SkillContent> | null
  version: number
}

/** 后台任务（决策 35）：任务中心/轮询共用结构。 */
export interface TaskItem {
  id: string
  type: string
  name: string
  status: 'queued' | 'running' | 'success' | 'failed' | 'not_found'
  progress: number
  stage: string
  result: Record<string, unknown> | null
  error: string | null
  related_id: number | null
  created_at: string | null
  finished_at: string | null
}
export interface ChapterContent {
  id: number
  index: number
  title: string
  content_text: string
  page_index: number | null
  word_count: number
  read_flag: boolean
}

export interface ReadingProgress {
  chapter_id: number | null
  position: number
  progress: number
  status: string
  last_opened_at: string | null
}

export interface AiSettings {
  base_url: string
  api_key: string
  api_key_set: boolean
  model: string
  mode: string
  timeout: number
  verify_ssl: boolean
  enable_body_send: boolean
  send_page_image: boolean
  temperature: number | null
  max_tokens: number | null
  thinking_type: string
  reasoning_effort: string
  top_p: number | null
  frequency_penalty: number | null
  presence_penalty: number | null
  stop: string
  vision_base_url: string
  vision_api_key: string
  vision_api_key_set: boolean
  vision_model: string
  vision_timeout: number
  vision_verify_ssl: boolean
  vision_max_tokens: number
  vision_temperature: number | null
  vision_top_p: number | null
  vision_frequency_penalty: number | null
  vision_presence_penalty: number | null
  vision_enable_thinking: boolean
  vision_thinking_budget: number | null
}

export interface ChatMessageItem {
  id: number
  role: 'user' | 'assistant'
  content: string
  /** 方案2 流式滚动落库键：前端轮询时按此键匹配进行中的回答。 */
  stream_key?: string | null
  book_id: number | null
  chapter_id: number | null
  ref_para_pos: string | null
  created_at: string | null
}

export type ChatStreamEvent =
  | { type: 'start' }
  | { type: 'thinking'; text: string }
  | { type: 'delta'; text: string }
  | { type: 'end'; text: string; citations: { chapter: number; para: string }[]; cached?: boolean }
  | { type: 'error'; message: string }

export type NoteType = '高亮' | '批注' | '思考' | '不理解'

export interface MindMapRef {
  chapter: number
  para: string
}

export interface MindMapNode {
  name: string
  nodeType?: '大纲' | '细节' | '重要定理'
  ref?: MindMapRef | null
  children?: MindMapNode[]
}

export interface MindMapResult {
  title: string
  tree: MindMapNode
  markdown: string
  citations: { chapter: number; para: string }[]
  /** 命中 LLM 结果缓存直接回放（性能优化 §7 决策 5）。 */
  cached?: boolean
}

/** 位置书签（全格式）。 */
export interface BookmarkItem {
  id: number
  book_id: number
  chapter_id: number | null
  page_index: number | null
  para_pos: string | null
  title: string
  note: string
  group_name: string
  created_at: string | null
}

/** 页图涂鸦元素（坐标均为相对页宽高的 0~1 归一化值）。 */
export interface AnnotationElement {
  type: 'stroke' | 'text'
  tool?: 'pen' | 'highlight'
  color?: string
  line_width?: number
  points?: [number, number][]
  text?: string
  font_size?: number
  x?: number
  y?: number
  note?: string
  note_meta?: { created_at: string; updated_at: string } | null
}

export interface NoteItem {
  id: number
  book_id: number
  chapter_id: number | null
  quote_text: string
  note_text: string
  note_type: NoteType
  created_at: string | null
}
/* ---------- M8 知识图谱 ---------- */
export interface GraphCluster {
  name: string
  book_ids: number[]
  book_count: number
}
export interface GraphNode {
  id: number
  title: string
  cluster: string
  tags: string[]
  format: string
  chapter_count: number
  graph_built: boolean
  status: string
}
export interface GraphEdge {
  id: number
  book_a: number
  book_b: number
  strength: number
  direction: string
  /** 有向边的理论源头书 id（direction 非「无」时箭头 from_book → 另一本） */
  from_book: number | null
  relation_type: string
  reasons: string[]
  user_feedback: string | null
}
export interface GlobalGraph {
  clusters: GraphCluster[]
  nodes: GraphNode[]
  edges: GraphEdge[]
  /** 懒构建中（后台化）：building=true 时 task_id 供轮询后重新拉取 */
  building?: boolean
  task_id?: string
}
export interface KpNode {
  id: number
  chapter_id: number | null
  title: string
  summary: string
  importance: number
  level: string
  para_pos: string | null
}
export interface KpEdge {
  from: number
  to: number
  relation_type: string
  strength: number
  note: string
}
export interface IntraGraph {
  nodes: KpNode[]
  edges: KpEdge[]
  chapters: { id: number; index: number; title: string }[]
  /** 懒构建中（后台化）：building=true 时 task_id 供轮询后重新拉取 */
  building?: boolean
  task_id?: string
}
/** 跨书检索：该知识点还出现在哪些书（M8 待办）。 */
export interface KnowledgeAppearsIn {
  source: {
    kp_id: number
    book_id: number
    title: string
    summary: string
    level: string
    para_pos: string | null
    chapter_id: number | null
  }
  books: {
    book_id: number
    title: string
    matched_kps: { id: number; title: string; level: string; chapter_id: number | null; para_pos: string | null; common: string[] }[]
    rag_hits: string[]
    matched_count: number
  }[]
  total: number
}
export interface ProfileLayer {
  [key: string]: unknown
}
export interface ProfileData {
  cold: ProfileLayer
  warm: ProfileLayer
  hot: ProfileLayer
}

export interface RecommendStats {
  archived_books: number
  notes: number
  questions: number
  chat_messages: number
  read_chapters: number
  books_total: number
}
export interface WeakConcept {
  concept: string
  count: number
}
export interface ReviewItem {
  book_id: number | null
  title: string
  days_ago: number
  due: boolean
}
export interface RhythmAdvice {
  level: string
  archived_books: number
  tip: string
}
export interface RecommendationsData {
  stats: RecommendStats
  weak_concepts: WeakConcept[]
  review: ReviewItem[]
  rhythm: RhythmAdvice
}

/** 画像阈值与学习状态（需求 3.4.1：系统自动学习，可手动覆盖）。 */
export interface ProfileThresholds {
  warm_threshold: number
  related_strength: number
  review_days: number
  learning: {
    sample_count: number
    related_sample_count: number
    last_learned_at: string | null
    learned: Record<string, unknown> | null
    min_samples: number
    confirmed_edges_min: number
    related_samples_min: number
  }
}
