/**
 * useSearchReplace：查找替换能力封装（纯函数 composable）。
 *
 * 实现思路：
 * - 通过 ProseMirror Plugin + DecorationSet 高亮匹配文本。
 * - composable 持有响应式状态（query/选项/匹配/当前索引），为 UI 面板数据源。
 * - plugin.state.apply 在「收到 search meta」或「文档变化」时重算匹配并重建装饰：
 *   匹配位置由 findMatches 遍历文档文本节点 + 正则得到，当前匹配加 --current 类。
 * - replaceOne/replaceAll 用 Transaction.insertText 替换文本（全部替换从后往前，单事务）。
 * - 不在 transaction 事件中 dispatch（避免重入）；仅在 Vue watcher/按钮回调中 dispatch meta。
 */
import { ref, watch, onUnmounted, type Ref, type ShallowRef } from 'vue'
import type { Editor } from '@tiptap/core'
import { Plugin, PluginKey, type EditorState, type Transaction } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import type { Node as ProseMirrorNode } from '@tiptap/pm/model'

/** 单条匹配位置（文档绝对坐标） */
export interface SearchMatch {
  from: number
  to: number
}

/** 搜索参数快照（plugin apply 时读取，避免闭包陈旧） */
interface SearchState {
  query: string
  caseSensitive: boolean
  wholeWord: boolean
  useRegex: boolean
  currentIndex: number
}

const searchPluginKey = new PluginKey<DecorationSet>('wordEditorSearch')

/**
 * 根据搜索参数构建正则（无效正则返回 null）。
 * - 非正则模式转义元字符；全字匹配用 \b 包裹。
 * - 全局匹配（g），大小写敏感时去掉 i。
 */
const buildRegex = (state: SearchState): RegExp | null => {
  const { query, caseSensitive, wholeWord, useRegex } = state
  if (!query) return null
  let pattern = useRegex ? query : query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  if (wholeWord) pattern = `\\b${pattern}\\b`
  const flags = caseSensitive ? 'g' : 'gi'
  try {
    return new RegExp(pattern, flags)
  } catch {
    return null
  }
}

/** 遍历文档文本节点，收集所有匹配的 {from, to} 位置 */
const findMatches = (doc: ProseMirrorNode, regex: RegExp): SearchMatch[] => {
  const found: SearchMatch[] = []
  doc.descendants((node, pos) => {
    if (!node.isText || !node.text) return
    const text = node.text
    regex.lastIndex = 0
    let m: RegExpExecArray | null
    while ((m = regex.exec(text)) !== null) {
      if (m[0] === '') {
        // 零宽匹配：推进避免死循环
        regex.lastIndex++
        continue
      }
      found.push({ from: pos + m.index, to: pos + m.index + m[0].length })
    }
  })
  return found
}

export interface UseSearchReplaceReturn {
  query: Ref<string>
  replacement: Ref<string>
  caseSensitive: Ref<boolean>
  wholeWord: Ref<boolean>
  useRegex: Ref<boolean>
  matches: Ref<SearchMatch[]>
  currentIndex: Ref<number>
  search: () => void
  next: () => void
  prev: () => void
  replaceOne: () => void
  replaceAll: () => void
  clear: () => void
}

/**
 * 查找替换 composable。
 * @param editor 编辑器实例引用（可能为 undefined）
 */
export function useSearchReplace(editor: ShallowRef<Editor | undefined> | Ref<Editor | undefined>): UseSearchReplaceReturn {
  const query = ref('')
  const replacement = ref('')
  const caseSensitive = ref(false)
  const wholeWord = ref(false)
  const useRegex = ref(false)
  const matches = ref<SearchMatch[]>([])
  const currentIndex = ref(0)

  /** 读取当前搜索参数快照（供 plugin apply 使用） */
  const readState = (): SearchState => ({
    query: query.value,
    caseSensitive: caseSensitive.value,
    wholeWord: wholeWord.value,
    useRegex: useRegex.value,
    currentIndex: currentIndex.value,
  })

  /** 同步匹配结果到响应式状态，并钳制当前索引 */
  const syncMatches = (found: SearchMatch[]): void => {
    matches.value = found
    if (currentIndex.value < 0 || currentIndex.value >= found.length) {
      currentIndex.value = 0
    }
  }

  /** 重算匹配并重建装饰（在 plugin apply 内调用） */
  const recompute = (state: EditorState): DecorationSet => {
    const opts = readState()
    if (!opts.query) {
      // 无激活查询：保持空装饰（matches 已由 watcher 清空）
      return DecorationSet.empty
    }
    const regex = buildRegex(opts)
    if (!regex) {
      syncMatches([])
      return DecorationSet.empty
    }
    const found = findMatches(state.doc, regex)
    syncMatches(found)
    const decos = found.map((m, i) =>
      Decoration.inline(m.from, m.to, {
        class: i === opts.currentIndex ? 'search-match search-match--current' : 'search-match',
      }),
    )
    return DecorationSet.create(state.doc, decos)
  }

  const searchPlugin = new Plugin<DecorationSet>({
    key: searchPluginKey,
    state: {
      init: () => DecorationSet.empty,
      apply: (tr: Transaction, oldSet: DecorationSet, _oldState: EditorState, newState: EditorState) => {
        const meta = tr.getMeta(searchPluginKey)
        // 收到 search meta 或文档变化时重算
        if (meta || tr.docChanged) {
          return recompute(newState)
        }
        // 仅光标移动等：保持现有装饰并映射位置
        return oldSet.map(tr.mapping, tr.doc)
      },
    },
    props: {
      decorations: (state: EditorState) => searchPluginKey.getState(state) ?? DecorationSet.empty,
    },
  })

  /** dispatch 一个 search meta，触发 plugin 重算并重绘装饰 */
  const dispatchSearch = (): void => {
    const inst = editor.value
    if (!inst || inst.isDestroyed) return
    inst.view.dispatch(inst.state.tr.setMeta(searchPluginKey, { type: 'search' }))
  }

  const search = (): void => {
    dispatchSearch()
  }

  const next = (): void => {
    if (matches.value.length === 0) return
    currentIndex.value = (currentIndex.value + 1) % matches.value.length
    dispatchSearch()
    scrollCurrentIntoView()
  }

  const prev = (): void => {
    if (matches.value.length === 0) return
    currentIndex.value = (currentIndex.value - 1 + matches.value.length) % matches.value.length
    dispatchSearch()
    scrollCurrentIntoView()
  }

  /** 滚动当前匹配到可视区域 */
  const scrollCurrentIntoView = (): void => {
    const inst = editor.value
    const m = matches.value[currentIndex.value]
    if (!inst || !m || inst.isDestroyed) return
    try {
      const dom = inst.view.domAtPos(m.from)
      const el = dom.node instanceof HTMLElement ? dom.node : dom.node.parentElement
      el?.scrollIntoView({ block: 'center', behavior: 'smooth' })
    } catch {
      // 忽略滚动定位异常
    }
  }

  const replaceOne = (): void => {
    const inst = editor.value
    const m = matches.value[currentIndex.value]
    if (!inst || inst.isDestroyed || !m) return
    // 替换当前匹配：insertText(text, from, to) 替换 [from,to] 范围
    inst.view.dispatch(inst.state.tr.insertText(replacement.value, m.from, m.to))
    // docChanged → plugin apply 重算，syncMatches 钳制当前索引
  }

  const replaceAll = (): void => {
    const inst = editor.value
    if (!inst || inst.isDestroyed || matches.value.length === 0) return
    // 从后往前替换，单事务内连续 insertText，避免位置偏移
    const sorted = [...matches.value].sort((a, b) => b.from - a.from)
    const tr = inst.state.tr
    for (const m of sorted) {
      tr.insertText(replacement.value, m.from, m.to)
    }
    inst.view.dispatch(tr)
  }

  const clear = (): void => {
    query.value = ''
    replacement.value = ''
    currentIndex.value = 0
    // query 变化由 watcher 触发重算并清空装饰
  }

  // 查询/选项变化 → 重置当前索引并重算
  watch([query, caseSensitive, wholeWord, useRegex], () => {
    currentIndex.value = 0
    dispatchSearch()
  })

  // 编辑器就绪后注册 plugin；卸载/切换时反注册
  watch(
    editor,
    (inst, _old, onCleanup) => {
      if (!inst) return
      inst.registerPlugin(searchPlugin)
      onCleanup(() => {
        if (!inst.isDestroyed) inst.unregisterPlugin(searchPluginKey)
      })
    },
    { immediate: true },
  )

  onUnmounted(() => {
    const inst = editor.value
    if (inst && !inst.isDestroyed) {
      inst.unregisterPlugin(searchPluginKey)
    }
  })

  return {
    query,
    replacement,
    caseSensitive,
    wholeWord,
    useRegex,
    matches,
    currentIndex,
    search,
    next,
    prev,
    replaceOne,
    replaceAll,
    clear,
  }
}
