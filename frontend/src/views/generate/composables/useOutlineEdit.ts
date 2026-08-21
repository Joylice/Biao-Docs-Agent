/**
 * 大纲树编辑操作：增删/移动/升降级/文本更新 + 撤销重做。
 * 结构化操作前 push 快照；纯文本输入不入栈（交给浏览器原生撤销）。
 */
import { ref } from 'vue'
import { message } from 'ant-design-vue'
import { useUndoRedo } from '@/composables/useUndoRedo'
import type { OutlineTreeNode } from '@/types'

let nodeKeySeed = 0
const nextNodeKey = () => `n${Date.now()}_${nodeKeySeed++}`

export const newNodeKey = nextNodeKey

export function useOutlineEdit() {
  /**
   * 大纲结构化编辑撤销/重做：editedTree 即快照栈的 state。
   * 增/删/移动/升降级操作前 push 快照；纯文本输入不入栈（交给浏览器原生撤销）。
   */
  const outlineHistory = useUndoRedo<OutlineTreeNode[]>([])
  const editedTree = outlineHistory.state
  const activeNodeKey = ref('')

  /* ---------------- 树操作 ---------------- */
  const findNodePath = (nodes: OutlineTreeNode[], key: string): number[] | null => {
    for (let i = 0; i < nodes.length; i += 1) {
      if (nodes[i].key === key) return [i]
      if (nodes[i].children?.length) {
        const found = findNodePath(nodes[i].children!, key)
        if (found) return [i, ...found]
      }
    }
    return null
  }

  const nodeAt = (path: number[] | null): OutlineTreeNode | null => {
    if (!path) return null
    let nodes: OutlineTreeNode[] = editedTree.value
    let cur: OutlineTreeNode | null = null
    for (const i of path) {
      cur = nodes[i]
      if (!cur) return null
      nodes = cur.children ?? []
    }
    return cur
  }

  const nodeListAndIndex = (path: number[] | null): [OutlineTreeNode[], number] | null => {
    if (!path) return null
    const list = path.length > 1 ? nodeAt(path.slice(0, -1))?.children : editedTree.value
    if (!list) return null
    return [list, path[path.length - 1]]
  }

  const handleAddChapter = () => {
    outlineHistory.push(editedTree.value)
    editedTree.value.push({ key: nextNodeKey(), title: '', covered_clauses: [] })
  }

  const handleAddChild = (key: string) => {
    const path = findNodePath(editedTree.value, key)
    const node = nodeAt(path)
    if (!node || !path) return
    if (path.length >= 4) { message.warning('最多支持 4 级层级'); return }
    outlineHistory.push(editedTree.value)
    node.children = node.children ?? []
    node.children.push({ key: nextNodeKey(), title: '' })
  }

  const handleRemoveNode = (key: string) => {
    const pair = nodeListAndIndex(findNodePath(editedTree.value, key))
    if (!pair) return
    outlineHistory.push(editedTree.value)
    pair[0].splice(pair[1], 1)
    if (activeNodeKey.value === key) activeNodeKey.value = ''
  }

  const handleMoveNode = (key: string, dir: -1 | 1) => {
    const pair = nodeListAndIndex(findNodePath(editedTree.value, key))
    if (!pair) return
    const [list, idx] = pair
    const j = idx + dir
    if (j < 0 || j >= list.length) return
    outlineHistory.push(editedTree.value)
    const tmp = list[idx]; list[idx] = list[j]; list[j] = tmp
  }

  const handlePromoteNode = (key: string) => {
    const path = findNodePath(editedTree.value, key)
    if (!path || path.length >= 4) return
    const pair = nodeListAndIndex(path)
    if (!pair || pair[1] === 0) return
    outlineHistory.push(editedTree.value)
    const [list, idx] = pair
    const prev = list[idx - 1]
    prev.children = prev.children ?? []
    prev.children.push(list[idx])
    list.splice(idx, 1)
  }

  const handleDemoteNode = (key: string) => {
    const path = findNodePath(editedTree.value, key)
    if (!path || path.length <= 1) return
    const parent = nodeAt(path.slice(0, -1))
    const grand = nodeListAndIndex(path.slice(0, -1))
    if (!parent || !grand) return
    outlineHistory.push(editedTree.value)
    const node = parent.children!.splice(path[path.length - 1], 1)[0]
    grand[0].splice(grand[1] + 1, 0, node)
  }

  const handleUpdateTitle = (key: string, title: string) => {
    const node = nodeAt(findNodePath(editedTree.value, key))
    if (node) node.title = title
  }

  const handleUpdateClauses = (key: string, text: string) => {
    const node = nodeAt(findNodePath(editedTree.value, key))
    if (!node) return
    node.covered_clauses = text.split(/[,，、]/).map((s) => s.trim()).filter(Boolean)
  }

  const onEditSelect = (key: string) => { activeNodeKey.value = key }

  /* ---------------- 大纲撤销/重做 ---------------- */
  /** 撤销后校正选中节点（快照中可能不含当前选中项） */
  const validateActiveNode = () => {
    if (activeNodeKey.value && !findNodePath(editedTree.value, activeNodeKey.value)) {
      activeNodeKey.value = ''
    }
  }

  const handleOutlineUndo = () => {
    if (!outlineHistory.undo()) {
      message.info('没有可撤销的大纲操作')
      return
    }
    validateActiveNode()
    message.success('已撤销上一步大纲操作')
  }

  const handleOutlineRedo = () => {
    if (!outlineHistory.redo()) {
      message.info('没有可重做的大纲操作')
      return
    }
    validateActiveNode()
    message.success('已重做大纲操作')
  }

  return {
    outlineHistory,
    editedTree,
    activeNodeKey,
    handleAddChapter,
    handleAddChild,
    handleRemoveNode,
    handleMoveNode,
    handlePromoteNode,
    handleDemoteNode,
    handleUpdateTitle,
    handleUpdateClauses,
    onEditSelect,
    handleOutlineUndo,
    handleOutlineRedo,
  }
}
