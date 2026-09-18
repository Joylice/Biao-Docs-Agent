/**
 * DSL 类型定义 — 与后端 app/services/content/dsl_types.py 对齐
 *
 * Block 类型覆盖投标方案文档的全部元素：
 * heading | paragraph | list | table | image | code_block
 *
 * 设计原则：DSL JSON 是存储/渲染/编辑的统一真源（参照 OpenMAIC @openmaic/dsl）
 */

export const DSL_VERSION = 1

export type BlockType =
  | 'heading'
  | 'paragraph'
  | 'list'
  | 'table'
  | 'image'
  | 'code_block'

export interface Citation {
  chunk_id: string
  doc_title: string
  page_no: number | null
}

export interface ListItem {
  content: string
  children: ListItem[]
}

export interface Block {
  type: BlockType
  // heading
  level?: number | null
  // heading / paragraph / code_block
  content: string
  // paragraph
  citations?: Citation[]
  // list
  ordered?: boolean | null
  items?: ListItem[]
  // table
  headers?: string[] | null
  rows?: string[][] | null
  style?: string | null
  // image
  url?: string
  alt?: string
  width_cm?: number | null
  // code_block
  language?: string | null
  // 通用样式
  attrs?: Record<string, unknown>
}

export interface ProposalContent {
  version: number
  blocks: Block[]
}

// ── 构造器（简化 Block 创建） ──

export const createBlock = (type: BlockType, partial: Partial<Block> = {}): Block => ({
  type,
  content: '',
  ...partial,
})

export const createContent = (blocks: Block[] = []): ProposalContent => ({
  version: DSL_VERSION,
  blocks,
})

// ── 类型守卫 ──

export const isHeading = (b: Block): b is Block & { type: 'heading' } => b.type === 'heading'
export const isParagraph = (b: Block): b is Block & { type: 'paragraph' } => b.type === 'paragraph'
export const isList = (b: Block): b is Block & { type: 'list' } => b.type === 'list'
export const isTable = (b: Block): b is Block & { type: 'table' } => b.type === 'table'
export const isImage = (b: Block): b is Block & { type: 'image' } => b.type === 'image'
export const isCodeBlock = (b: Block): b is Block & { type: 'code_block' } => b.type === 'code_block'
