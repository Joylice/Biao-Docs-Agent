import type { AssignmentNode, OutlineSection } from '@/types'

/** 分工树递归拍平：章行 + 子节 children */
export const flattenAssignmentNodes = (nodes: AssignmentNode[]): AssignmentNode[] =>
  nodes.flatMap((n) => [n, ...(n.children?.length ? flattenAssignmentNodes(n.children) : [])])

/** 大纲子节标题：字符串（LLM 原始）或 { title } 对象（编辑产物） */
export const sectionTitleOf = (section: OutlineSection): string =>
  typeof section === 'string' ? section : section.title
