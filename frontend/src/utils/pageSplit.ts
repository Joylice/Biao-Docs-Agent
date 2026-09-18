/**
 * pageSplit.ts — 分页预览的 DOM 文本切分工具（纯逻辑，无布局依赖，可单测）
 *
 * 约定：所有字符累计均按"文档顺序前序遍历 Text 节点"计（与浏览器文本流一致），
 * 供 PaginatedPreview 将超长文本块按字符预算切分为"页内部分 + 续页部分"。
 */

/** 累计元素内全部文本节点字符数 */
export function textLength(el: Element): number {
  let n = 0
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
  let node = walker.nextNode()
  while (node) {
    n += (node as Text).data.length
    node = walker.nextNode()
  }
  return n
}

/** 块级不可拆元素（表格/图片/代码/列表等整块换页；标题虽可拆但极少超高） */
const ATOMIC_TAGS = new Set([
  'TABLE', 'IMG', 'PRE', 'OL', 'UL', 'HR', 'BLOCKQUOTE', 'FIGURE', 'SVG',
  'IFRAME', 'VIDEO', 'AUDIO', 'CANVAS', 'OBJECT', 'EMBED',
])

/** 是否存在不可拆的块级后代（决定该块能否按字符切分跨页） */
export function hasAtomicDescendant(el: Element): boolean {
  return !!el.querySelector(Array.from(ATOMIC_TAGS).join(','))
}

/** 该块是否允许字符级切分（无原子后代且含文本） */
export function isSplittableTextBlock(el: Element): boolean {
  return !hasAtomicDescendant(el) && textLength(el) > 0
}

/**
 * 就地截断：仅保留文档顺序前 n 个字符，其后内容全部移除。
 * 若文本总数不足 n 则不变。返回实际保留字符数。
 */
export function truncateToChars(el: Element, n: number): number {
  if (n <= 0) {
    // 清空全部文本（保留标签骨架，保证结构合法）
    collectTextNodes(el).forEach((t) => t.remove())
    return 0
  }
  let remaining = n
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
  const toRemove: Text[] = []
  let node = walker.nextNode()
  while (node) {
    const t = node as Text
    if (remaining <= 0) {
      toRemove.push(t)
    } else if (t.data.length > remaining) {
      const tail = t.splitText(remaining) // tail 为剩余部分
      toRemove.push(tail)
      remaining = 0
    } else {
      remaining -= t.data.length
    }
    node = walker.nextNode()
  }
  toRemove.forEach((t) => t.remove())
  return Math.max(0, n - remaining)
}

/** 就地丢弃文档顺序前 n 个字符（保留尾部）。实际剩余字符数 = 总长 - min(n, 总长) */
export function dropCharsFromStart(el: Element, n: number): number {
  if (n <= 0) return textLength(el)
  let remaining = n
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
  const toRemove: Text[] = []
  let node = walker.nextNode()
  while (node) {
    const t = node as Text
    if (remaining <= 0) break
    if (t.data.length > remaining) {
      const keep = t.splitText(remaining)
      toRemove.push(t) // 前 remaining 字符丢弃
      remaining = 0
      void keep
    } else {
      remaining -= t.data.length
      toRemove.push(t)
    }
    node = walker.nextNode()
  }
  toRemove.forEach((t) => t.remove())
  return textLength(el)
}

/**
 * 将元素克隆为两段：[前 n 字符 head, 尾部 tail]。
 * head 可能为空文本（仅标签骨架）；调用方应检查 textLength 决定是否丢弃。
 */
export function splitAtChars(el: Element, n: number): [Element, Element] {
  const head = el.cloneNode(true) as Element
  truncateToChars(head, n)
  const tail = el.cloneNode(true) as Element
  dropCharsFromStart(tail, n)
  return [head, tail]
}

/** 收集元素下全部文本节点（文档顺序） */
function collectTextNodes(el: Element): Text[] {
  const out: Text[] = []
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT)
  let node = walker.nextNode()
  while (node) {
    out.push(node as Text)
    node = walker.nextNode()
  }
  return out
}

/** 清理解析出的顶层块中无实际内容（无文本且无 img/table 等）的空壳 */
export function hasVisibleContent(el: Element): boolean {
  if (textLength(el) > 0) return true
  return !!el.querySelector('img, table, hr, svg, video, iframe, figure')
}
