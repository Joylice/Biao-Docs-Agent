/**
 * 目录（TOC）生成工具
 * - 从编辑器文档中提取 H1-H4 标题
 * - 为标题生成唯一锚点 ID
 * - 生成嵌套目录 HTML
 * - 支持插入目录和更新目录
 */
import type { Editor } from '@tiptap/core'
import type { Node as PMNode } from '@tiptap/pm/model'

/** 目录项 */
export interface TocItem {
  /** 标题级别 1-4 */
  level: number
  /** 标题文本 */
  text: string
  /** 锚点 ID */
  id: string
  /** 子项 */
  children: TocItem[]
}

/** 目录配置 */
export interface TocOptions {
  /** 包含的标题级别，默认 [1, 2, 3] */
  levels?: number[]
  /** 目录标题，默认 "目录" */
  title?: string
  /** 是否显示页码（Web 端不支持真实页码，显示序号） */
  showPageNumber?: boolean
}

/**
 * 生成唯一 ID（基于标题文本和序号）
 */
function generateId(text: string, index: number): string {
  const slug = text
    .toLowerCase()
    .replace(/[^\w\u4e00-\u9fa5]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 30)
  return `heading-${slug || 'untitled'}-${index}`
}

/**
 * 从编辑器文档中提取标题列表
 */
export function extractHeadings(editor: Editor): Array<{ level: number; text: string; id: string }> {
  const headings: Array<{ level: number; text: string; id: string }> = []
  let index = 0

  editor.state.doc.descendants((node) => {
    if (node.type.name === 'heading') {
      const level = node.attrs.level as number
      const text = node.textContent || '未命名标题'
      // 使用节点的 id 属性，或生成一个
      const id = (node.attrs.id as string) || generateId(text, index++)
      headings.push({ level, text, id })
    }
  })

  return headings
}

/**
 * 将扁平标题列表转换为嵌套树结构
 */
export function buildTocTree(
  headings: Array<{ level: number; text: string; id: string }>,
  options: TocOptions = {},
): TocItem[] {
  const levels = options.levels ?? [1, 2, 3]
  const filtered = headings.filter((h) => levels.includes(h.level))

  const root: TocItem[] = []
  const stack: TocItem[] = []

  for (const heading of filtered) {
    const item: TocItem = {
      level: heading.level,
      text: heading.text,
      id: heading.id,
      children: [],
    }

    // 弹出栈中级别 >= 当前级别的项
    while (stack.length > 0 && stack[stack.length - 1].level >= heading.level) {
      stack.pop()
    }

    if (stack.length === 0) {
      root.push(item)
    } else {
      stack[stack.length - 1].children.push(item)
    }

    stack.push(item)
  }

  return root
}

/**
 * 将目录树渲染为 HTML
 */
export function renderTocHtml(tree: TocItem[], options: TocOptions = {}): string {
  const title = options.title ?? '目录'

  const renderList = (items: TocItem[]): string => {
    if (items.length === 0) return ''
    return `<ul class="toc-list">${items
      .map(
        (item) => `
        <li class="toc-item toc-level-${item.level}">
          <a href="#${item.id}" class="toc-link">${item.text}</a>
          ${renderList(item.children)}
        </li>`,
      )
      .join('')}</ul>`
  }

  return `
    <div class="toc-container" data-toc="true">
      <h2 class="toc-title" contenteditable="false">${title}</h2>
      ${renderList(tree)}
    </div>
  `
}

/**
 * 为文档中所有标题添加锚点 ID（如果没有）
 * 返回是否有修改
 */
export function ensureHeadingIds(editor: Editor): boolean {
  let modified = false
  let index = 0

  editor.state.doc.descendants((node) => {
    if (node.type.name === 'heading' && !node.attrs.id) {
      const text = node.textContent || '未命名标题'
      const id = generateId(text, index++)
      editor.chain().focus().updateAttributes('heading', { id }).run()
      modified = true
      return false // 停止遍历，因为事务已改变文档
    }
  })

  return modified
}

/**
 * 在当前光标位置插入目录
 */
export function insertToc(editor: Editor, options: TocOptions = {}): void {
  // 先确保所有标题有 ID
  ensureHeadingIds(editor)

  // 提取标题并生成目录
  const headings = extractHeadings(editor)
  const tree = buildTocTree(headings, options)
  const html = renderTocHtml(tree, options)

  // 插入到当前位置
  editor.chain().focus().insertContent(html).run()
}

/**
 * 更新文档中已有的目录
 * 返回是否找到并更新了目录
 */
export function updateToc(editor: Editor, options: TocOptions = {}): boolean {
  let tocPos = -1
  let tocNode: PMNode | null = null

  // 查找目录容器节点
  editor.state.doc.descendants((node, pos) => {
    if (node.type.name === 'paragraph' || node.type.name === 'div') {
      if (node.attrs['data-toc'] === 'true') {
        tocPos = pos
        tocNode = node
        return false
      }
    }
  })

  // 如果没找到，尝试通过 HTML 内容查找
  if (tocPos === -1) {
    const fullHtml = editor.getHTML()
    if (!fullHtml.includes('data-toc="true"')) {
      return false
    }
  }

  // 确保标题有 ID
  ensureHeadingIds(editor)

  // 生成新目录 HTML
  const headings = extractHeadings(editor)
  const tree = buildTocTree(headings, options)
  const newHtml = renderTocHtml(tree, options)

  // 简单方案：如果找到位置，替换该节点
  if (tocPos !== -1 && tocNode) {
    editor
      .chain()
      .focus()
      .insertContentAt(tocPos, newHtml)
      .run()
  } else {
    // 降级方案：在文档开头插入目录
    editor.chain().focus().insertContentAt(0, newHtml).run()
  }

  return true
}

/**
 * 跳转到指定标题
 */
export function scrollToHeading(editor: Editor, id: string): void {
  const dom = editor.view.dom
  const element = dom.querySelector(`[id="${id}"]`)
  if (element) {
    element.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}
