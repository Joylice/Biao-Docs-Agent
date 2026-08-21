/**
 * 大纲 ↔ 编辑树 结构转换（纯函数）.
 * 由 GenerateView 大纲编辑面板与草稿保存共用。
 */
import type { OutlineItem, OutlineSection, OutlineTreeNode } from '@/types'

let nodeKeySeed = 0
const nextNodeKey = () => `n${Date.now()}_${nodeKeySeed++}`

export const outlineToTree = (items: OutlineItem[]): OutlineTreeNode[] =>
  items.map((c) => ({
    key: nextNodeKey(),
    title: c.title,
    covered_clauses: [...(c.covered_clauses ?? [])],
    children: sectionsToTree(c.sections),
  }))

export const sectionsToTree = (sections?: OutlineSection[]): OutlineTreeNode[] => {
  if (!Array.isArray(sections)) return []
  return sections.map((s) =>
    typeof s === 'string'
      ? { key: nextNodeKey(), title: s }
      : { key: nextNodeKey(), title: s.title, children: sectionsToTree(s.children) },
  )
}

export const treeToOutline = (nodes: OutlineTreeNode[]): OutlineItem[] =>
  nodes.map((n, i) => ({
    chapter_no: String(i + 1),
    title: n.title.trim(),
    sections: treeToSections(n.children),
    covered_clauses: n.covered_clauses?.length ? n.covered_clauses : undefined,
  }))

export const treeToSections = (nodes?: OutlineTreeNode[]): OutlineSection[] | undefined => {
  if (!nodes?.length) return undefined
  return nodes.map((n) => {
    const children = treeToSections(n.children)
    return children?.length ? { title: n.title.trim(), children } : { title: n.title.trim() }
  })
}
