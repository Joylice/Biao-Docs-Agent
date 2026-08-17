/**
 * 方案大纲数据结构（二次编辑树形化后统一类型）。
 *
 * 后端 outline 章节结构：{chapter_no, title, sections, covered_clauses}
 * - sections 兼容两种形态：string[]（LLM 原始）或嵌套树 [{title, children}]（二次编辑产物）
 * - 二次编辑产物由前端树形编辑器生成，编号（1 / 1.1 / 1.1.1）由位置推导、提交时重算
 */

/** 编辑树节点（本地唯一 key 仅用于编辑态交互，提交时丢弃） */
export interface OutlineTreeNode {
  key: string
  title: string
  /** 覆盖的评分点条款号（仅章节节点使用） */
  covered_clauses?: string[]
  children?: OutlineTreeNode[]
}

/** 子节：字符串（LLM 原始）或嵌套树节点（编辑产物） */
export type OutlineSection = string | { title: string; children?: OutlineSection[] }

/** 后端大纲章节结构 */
export interface OutlineItem {
  chapter_no: string
  title: string
  sections?: OutlineSection[]
  covered_clauses?: string[]
}
