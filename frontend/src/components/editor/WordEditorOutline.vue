<template>
  <div
    class="word-outline"
    :class="{ 'word-outline--collapsed': !visible }"
  >
    <div class="word-outline__header">
      <span class="word-outline__title">大纲</span>
      <a-button
        type="text"
        size="small"
        aria-label="收起大纲"
        @click="close"
      >
        <template #icon>
          <CloseOutlined />
        </template>
      </a-button>
    </div>

    <div class="word-outline__body">
      <div
        v-if="flatList.length === 0"
        class="word-outline__empty"
      >
        暂无标题，请添加 H1-H3 标题生成大纲
      </div>
      <ul
        v-else
        class="word-outline__list"
      >
        <li
          v-for="item in flatList"
          :key="item.id"
          class="word-outline__item"
          :class="{
            'word-outline__item--active': item.id === activeId,
          }"
          :style="{ '--outline-depth': item.depth }"
        >
          <span class="word-outline__item-inner">
            <!-- 折叠/展开按钮 -->
            <button
              v-if="item.hasChildren"
              type="button"
              class="word-outline__toggle"
              :aria-label="collapsedIds.has(item.id) ? '展开' : '折叠'"
              @click="toggleCollapse(item.id)"
            >
              <CaretRightOutlined
                :class="{ 'word-outline__toggle-icon--expanded': !collapsedIds.has(item.id) }"
              />
            </button>
            <span
              v-else
              class="word-outline__toggle-placeholder"
            />

            <!-- 标题文本 + 字数 -->
            <button
              type="button"
              class="word-outline__text"
              :class="`word-outline__text--h${item.level}`"
              :title="item.text"
              @click="jumpTo(item)"
            >
              <span class="word-outline__text-content">{{ item.text || `标题 ${item.level}` }}</span>
            </button>
            <span class="word-outline__count">{{ item.wordCount }} 字</span>
          </span>
        </li>
      </ul>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * WordEditorOutline：左侧大纲导航面板
 *
 * 功能：
 * - 从 editor doc 递归提取 H1/H2/H3 构建树结构，debounce 300ms 重建
 * - 树形展示（自研 ul/li + 缩进），支持折叠/展开
 * - 点击标题跳转：setTextSelection + scrollIntoView
 * - 滚动高亮当前章节：IntersectionObserver 监听编辑区 h1/h2/h3
 * - 章节字数统计：heading 下游直到下一个同级/更高级 heading
 *
 * @param editor 编辑器实例
 * @param visible 控制面板显示/隐藏（收起时 width: 0）
 */
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import type { Editor } from '@tiptap/core'
import type { Node as ProseMirrorNode } from '@tiptap/pm/model'
import { CaretRightOutlined, CloseOutlined } from '@ant-design/icons-vue'

/* ---------------- 类型定义 ---------------- */

/** 大纲节点（树结构） */
interface OutlineNode {
  /** 唯一标识（基于文档位置） */
  id: string
  /** 标题级别 1-3 */
  level: number
  /** 标题文本 */
  text: string
  /** 子节点 */
  children: OutlineNode[]
  /** 在文档中的绝对位置（节点起始偏移） */
  pos: number
}

/** 扁平化展示项（含缩进深度 + 字数） */
interface FlatOutlineItem extends OutlineNode {
  /** 缩进深度（0 = H1 顶层） */
  depth: number
  /** 是否有子节点 */
  hasChildren: boolean
  /** 章节字数 */
  wordCount: number
}

const props = defineProps<{
  /** 编辑器实例 */
  editor: Editor | undefined
  /** 是否显示面板 */
  visible: boolean
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
}>()

/* ---------------- 响应式状态 ---------------- */

/** 大纲树（根级节点数组） */
const outlineTree = ref<OutlineNode[]>([])
/** 全部标题扁平列表（与 DOM h1-h3 顺序一致，供 observer 匹配） */
const allHeadings = ref<OutlineNode[]>([])
/** 扁平化展示列表（受折叠状态影响） */
const flatList = ref<FlatOutlineItem[]>([])
/** 折叠的节点 ID 集合 */
const collapsedIds = ref<Set<string>>(new Set())
/** 当前高亮的标题 ID */
const activeId = ref<string | null>(null)

/* ---------------- 大纲构建 ---------------- */

/** 从 doc 构建扁平标题列表（按文档顺序） */
const extractHeadings = (doc: ProseMirrorNode): OutlineNode[] => {
  const flat: OutlineNode[] = []
  doc.forEach((node, offset) => {
    if (node.type.name === 'heading') {
      const level = node.attrs.level as number
      if (level >= 1 && level <= 3) {
        flat.push({
          id: `heading-${offset}`,
          level,
          text: node.textContent,
          children: [],
          pos: offset,
        })
      }
    }
  })
  return flat
}

/** 将扁平标题列表构建为树（基于层级嵌套） */
const buildTree = (flat: OutlineNode[]): OutlineNode[] => {
  const root: OutlineNode[] = []
  const stack: OutlineNode[] = []
  for (const node of flat) {
    // 弹出栈中级别 >= 当前的节点（同级或更高级的后续）
    while (stack.length > 0 && stack[stack.length - 1].level >= node.level) {
      stack.pop()
    }
    if (stack.length === 0) {
      root.push(node)
    } else {
      stack[stack.length - 1].children.push(node)
    }
    stack.push(node)
  }
  return root
}

/** 计算每个标题的章节字数（该标题到下一个同级/更高级标题之间的文本） */
const computeWordCounts = (doc: ProseMirrorNode, headings: OutlineNode[]): Map<string, number> => {
  const counts = new Map<string, number>()
  for (let i = 0; i < headings.length; i++) {
    const current = headings[i]
    // 查找下一个同级或更高级标题的位置
    let endPos = doc.content.size
    for (let j = i + 1; j < headings.length; j++) {
      if (headings[j].level <= current.level) {
        endPos = headings[j].pos
        break
      }
    }
    // 提取当前标题到结束位置之间的文本
    const text = doc.textBetween(current.pos, endPos, ' ', ' ')
    counts.set(current.id, text.replace(/\s/g, '').length)
  }
  return counts
}

/** 扁平化树为展示列表（受折叠状态影响） */
const flattenTree = (nodes: OutlineNode[], counts: Map<string, number>, depth = 0): FlatOutlineItem[] => {
  const result: FlatOutlineItem[] = []
  for (const node of nodes) {
    const hasChildren = node.children.length > 0
    result.push({
      ...node,
      depth,
      hasChildren,
      wordCount: counts.get(node.id) ?? 0,
    })
    if (hasChildren && !collapsedIds.value.has(node.id)) {
      result.push(...flattenTree(node.children, counts, depth + 1))
    }
  }
  return result
}

/** 重建大纲（从 editor doc 提取 → 建树 → 扁平化 → 更新 observer） */
const rebuildOutline = () => {
  const inst = props.editor
  if (!inst || inst.isDestroyed) {
    outlineTree.value = []
    allHeadings.value = []
    flatList.value = []
    return
  }
  const doc = inst.state.doc
  const flat = extractHeadings(doc)
  const tree = buildTree(flat)
  const counts = computeWordCounts(doc, flat)

  outlineTree.value = tree
  allHeadings.value = flat
  flatList.value = flattenTree(tree, counts)

  // 重建后更新 IntersectionObserver
  setupObserver()
}

/** debounce 重建（避免频繁 transaction 触发重建） */
let rebuildTimer: ReturnType<typeof setTimeout> | null = null
const scheduleRebuild = () => {
  if (rebuildTimer) clearTimeout(rebuildTimer)
  rebuildTimer = setTimeout(() => {
    rebuildOutline()
    rebuildTimer = null
  }, 300)
}

/* ---------------- 折叠/展开 ---------------- */

const toggleCollapse = (id: string) => {
  const next = new Set(collapsedIds.value)
  if (next.has(id)) {
    next.delete(id)
  } else {
    next.add(id)
  }
  collapsedIds.value = next
  // 重新扁平化（无需重建大纲，只需重算展示列表）
  const inst = props.editor
  if (inst && !inst.isDestroyed) {
    const counts = computeWordCounts(inst.state.doc, allHeadings.value)
    flatList.value = flattenTree(outlineTree.value, counts)
  }
}

/* ---------------- 点击跳转 ---------------- */

const jumpTo = (node: OutlineNode) => {
  const inst = props.editor
  if (!inst || inst.isDestroyed) return
  // 选中该标题节点
  inst.chain().focus().setTextSelection(node.pos).run()
  // 滚动到标题元素
  try {
    const dom = inst.view.domAtPos(node.pos)
    const el = dom.node instanceof HTMLElement ? dom.node : dom.node.parentElement
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  } catch {
    // 滚动定位异常时忽略
  }
  activeId.value = node.id
}

/* ---------------- IntersectionObserver 滚动高亮 ---------------- */

let observer: IntersectionObserver | null = null

const setupObserver = () => {
  const inst = props.editor
  if (!inst || inst.isDestroyed) return
  observer?.disconnect()

  // 滚动容器：编辑区的 .word-editor__scroll
  const root = inst.view.dom.closest('.word-editor__scroll') as HTMLElement | null
  if (!root || typeof IntersectionObserver === 'undefined') return

  // 查询编辑区内所有 h1/h2/h3（与 allHeadings 顺序一致）
  const domHeadings = Array.from(inst.view.dom.querySelectorAll('h1, h2, h3'))
  if (domHeadings.length === 0) return

  observer = new IntersectionObserver(
    (entries) => {
      // 取最靠顶部的可见标题
      const visible = entries
        .filter((e) => e.isIntersecting)
        .sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
      if (visible.length > 0) {
        const index = domHeadings.indexOf(visible[0].target as Element)
        if (index >= 0 && index < allHeadings.value.length) {
          activeId.value = allHeadings.value[index].id
        }
      }
    },
    // rootMargin: 顶部 0，底部 -80% → 仅当标题进入视口上部 20% 时高亮
    { root, rootMargin: '0px 0px -80% 0px', threshold: 0 },
  )

  domHeadings.forEach((el) => observer?.observe(el))
}

/* ---------------- editor 事务监听 ---------------- */

watch(
  () => props.editor,
  (inst, _old, onCleanup) => {
    if (!inst) return
    // 初始构建
    rebuildOutline()
    // 事务变化 → debounce 重建
    inst.on('transaction', scheduleRebuild)
    onCleanup(() => {
      inst.off('transaction', scheduleRebuild)
      observer?.disconnect()
    })
  },
  { immediate: true },
)

/* ---------------- 面板关闭 ---------------- */

const close = () => {
  emit('update:visible', false)
}

/* ---------------- 生命周期 ---------------- */

onMounted(() => {
  // 确保 editor 就绪后构建（watch immediate 已处理，此处兜底）
  if (props.editor && outlineTree.value.length === 0) {
    rebuildOutline()
  }
})

onBeforeUnmount(() => {
  observer?.disconnect()
  if (rebuildTimer) clearTimeout(rebuildTimer)
})
</script>

<style scoped>
.word-outline {
  flex: 0 0 auto;
  width: 240px;
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  border-right: 1px solid var(--border-color);
  overflow: hidden;
  transition: width var(--transition-normal);
}

/* 收起状态：宽度归零 */
.word-outline--collapsed {
  width: 0;
  border-right: none;
}

/* 面板头部 */
.word-outline__header {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 36px;
  padding: 0 var(--space-2) 0 var(--space-3);
  border-bottom: 1px solid var(--border-color);
}
.word-outline__title {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--text-primary);
}

/* 面板主体（可滚动） */
.word-outline__body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--space-1) 0;
}

/* 空状态 */
.word-outline__empty {
  padding: var(--space-6) var(--space-3);
  text-align: center;
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
}

/* 大纲列表 */
.word-outline__list {
  list-style: none;
  margin: 0;
  padding: 0;
}

/* 大纲条目 */
.word-outline__item {
  padding-left: calc(var(--outline-depth, 0) * 16px + var(--space-2));
}
.word-outline__item-inner {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 2px var(--space-2);
  border-radius: var(--radius-xs);
  transition: background var(--transition-fast);
  cursor: default;
}
.word-outline__item-inner:hover {
  background: var(--bg-surface-hover);
}
/* 激活态高亮 */
.word-outline__item--active .word-outline__item-inner {
  background: var(--color-primary-light);
}
.word-outline__item--active .word-outline__text {
  color: var(--color-primary);
  font-weight: 600;
}

/* 折叠/展开按钮 */
.word-outline__toggle {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border: none;
  background: none;
  cursor: pointer;
  padding: 0;
  color: var(--text-tertiary);
  font-size: 10px;
  transition: transform var(--transition-fast), color var(--transition-fast);
}
.word-outline__toggle:hover {
  color: var(--text-primary);
}
.word-outline__toggle-icon--expanded {
  transform: rotate(90deg);
}
/* 无子节点时的占位 */
.word-outline__toggle-placeholder {
  flex: 0 0 16px;
}

/* 标题文本按钮 */
.word-outline__text {
  flex: 1;
  min-width: 0;
  border: none;
  background: none;
  cursor: pointer;
  padding: 2px 4px;
  text-align: left;
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: color var(--transition-fast);
}
.word-outline__text:hover {
  color: var(--text-primary);
}
/* 不同级别标题的字号区分 */
.word-outline__text--h1 {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--text-primary);
}
.word-outline__text--h2 {
  font-size: var(--font-size-sm);
  color: var(--text-primary);
}
.word-outline__text--h3 {
  font-size: var(--font-size-xs);
}
.word-outline__text-content {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 章节字数 */
.word-outline__count {
  flex: 0 0 auto;
  font-size: 10px;
  color: var(--text-tertiary);
  white-space: nowrap;
}

/* 深色模式微调 */
[data-theme='dark'] .word-outline__item--active .word-outline__item-inner {
  background: var(--color-primary-light);
}
</style>
