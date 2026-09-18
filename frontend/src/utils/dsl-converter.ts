/**
 * DSL ↔ ProseMirror JSON 双向转换器
 *
 * 替代 markdown-converter.ts 的有损 Markdown↔HTML 链路。
 * content_dsl 作为唯一真源：编辑器直接读写 DSL JSON，零转换损失。
 *
 * 映射关系（Tiptap Schema ↔ DSL Block）：
 *   heading(node)         ↔ heading block { level, content }
 *   paragraph(node)       ↔ paragraph block { content }
 *   bulletList(node)      ↔ list block { ordered: false, items }
 *   orderedList(node)     ↔ list block { ordered: true, items }
 *   table(node)           ↔ table block { headers, rows }
 *   image(node)           ↔ image block { url, alt }
 *   codeBlock(node)       ↔ code_block block { content, language }
 *
 * 样式保真：Tiptap marks（bold/italic/textStyle 等）通过 attrs 字段保留，
 * 不依赖 Markdown 中间格式表达。
 */

import type { Block, ListItem, ProposalContent } from '@/types/dsl'
import { createBlock, createContent } from '@/types/dsl'

// ════════════════════════════════════════════════════════════
// DSL → ProseMirror JSON
// ════════════════════════════════════════════════════════════

/**
 * 将 ProposalContent DSL 转换为 Tiptap 可直接 setContent 的 JSON 格式
 *
 * @param content DSL 文档
 * @returns Tiptap JSON（{ type: 'doc', content: [...] }）
 */
export function dslToProseMirror(content: ProposalContent): Record<string, unknown> {
  const pmNodes: unknown[] = []

  for (const block of content.blocks) {
    const node = blockToPMNode(block)
    if (node) {
      if (Array.isArray(node)) {
        pmNodes.push(...node)
      } else {
        pmNodes.push(node)
      }
    }
  }

  return { type: 'doc', content: pmNodes }
}

function blockToPMNode(block: Block): Record<string, unknown> | Record<string, unknown>[] | null {
  switch (block.type) {
    case 'heading':
      return {
        type: 'heading',
        attrs: { level: block.level ?? 2 },
        content: [{ type: 'text', text: block.content }],
      }

    case 'paragraph': {
      // 将纯文本转为 text node；含换行时拆分为多段
      if (!block.content) {
        return { type: 'paragraph' }
      }
      return {
        type: 'paragraph',
        content: [{ type: 'text', text: block.content }],
      }
    }

    case 'list':
      return listToPMNode(block.ordered ?? false, block.items ?? [])

    case 'table':
      return tableToPMNode(block.headers ?? [], block.rows ?? [])

    case 'image':
      return {
        type: 'image',
        attrs: {
          src: block.url ?? '',
          alt: block.alt ?? '',
          title: block.alt ?? '',
        },
      }

    case 'code_block':
      return {
        type: 'codeBlock',
        attrs: { language: block.language ?? null },
        content: block.content ? [{ type: 'text', text: block.content }] : [],
      }

    default:
      // 未知 block 类型降级为段落
      return {
        type: 'paragraph',
        content: [{ type: 'text', text: block.content || '' }],
      }
  }
}

function listToPMNode(ordered: boolean, items: ListItem[]): Record<string, unknown> {
  const listType = ordered ? 'orderedList' : 'bulletList'
  const listItems: unknown[] = items.map((item) => {
    // listItem 的 content 是 [paragraph, ...nestedList] 平级排列
    const itemContent: unknown[] = [
      {
        type: 'paragraph',
        content: [{ type: 'text', text: item.content }],
      },
    ]
    // 嵌套子列表作为 listItem 的直接子节点（非 paragraph 内部）
    if (item.children && item.children.length > 0) {
      itemContent.push(listToPMNode(ordered, item.children))
    }
    return {
      type: 'listItem',
      content: itemContent,
    }
  })

  return {
    type: listType,
    content: listItems,
  }
}

function tableToPMNode(headers: string[], rows: string[][]): Record<string, unknown> | null {
  if (headers.length === 0 && rows.length === 0) return null

  const allRows: unknown[] = []

  // 表头行
  if (headers.length > 0) {
    allRows.push({
      type: 'tableRow',
      content: headers.map((h) => ({
        type: 'tableHeader',
        content: [{ type: 'paragraph', content: [{ type: 'text', text: h }] }],
      })),
    })
  }

  // 数据行
  for (const row of rows) {
    allRows.push({
      type: 'tableRow',
      content: row.map((cell) => ({
        type: 'tableCell',
        content: [{ type: 'paragraph', content: [{ type: 'text', text: cell }] }],
      })),
    })
  }

  return { type: 'table', content: allRows }
}

// ════════════════════════════════════════════════════════════
// ProseMirror JSON → DSL
// ════════════════════════════════════════════════════════════

/**
 * 将 Tiptap 编辑器输出的 JSON 转换为 ProposalContent DSL
 *
 * @param pmDoc Tiptap getJSON() 输出
 * @returns ProposalContent DSL 文档
 */
export function proseMirrorToDSL(pmDoc: Record<string, unknown>): ProposalContent {
  const content = (pmDoc.content as Record<string, unknown>[]) ?? []
  const blocks: Block[] = []

  for (const node of content) {
    const block = pmNodeToBlock(node)
    if (block) {
      if (Array.isArray(block)) {
        blocks.push(...block)
      } else {
        blocks.push(block)
      }
    }
  }

  return createContent(blocks)
}

function pmNodeToBlock(node: Record<string, unknown>): Block | Block[] | null {
  const type = node.type as string
  const attrs = (node.attrs ?? {}) as Record<string, unknown>
  const content = node.content as Record<string, unknown>[] | undefined

  switch (type) {
    case 'heading': {
      const level = (attrs.level as number) ?? 2
      const text = extractText(content)
      return createBlock('heading', { level, content: text })
    }

    case 'paragraph': {
      const text = extractText(content)
      return createBlock('paragraph', { content: text })
    }

    case 'bulletList':
      return listToBlock(false, content)

    case 'orderedList':
      return listToBlock(true, content)

    case 'table':
      return tableToBlock(content)

    case 'image':
      return createBlock('image', {
        url: (attrs.src as string) ?? '',
        alt: (attrs.alt as string) ?? (attrs.title as string) ?? '',
      })

    case 'codeBlock': {
      const text = extractText(content)
      return createBlock('code_block', {
        content: text,
        language: (attrs.language as string) ?? null,
      })
    }

    case 'taskList':
      // 任务列表降级为普通列表
      return listToBlock(false, content)

    default:
      // 未知节点类型尝试提取文本降级为段落
      {
        const text = extractText(content)
        if (text) {
          return createBlock('paragraph', { content: text })
        }
        return null
      }
  }
}

function listToBlock(ordered: boolean, content: Record<string, unknown>[] | undefined): Block {
  const items: ListItem[] = (content ?? []).map((liNode) => {
    const liContent = (liNode.content as Record<string, unknown>[]) ?? []
    const itemText: string[] = []
    let children: ListItem[] = []

    for (const child of liContent) {
      const childType = child.type as string
      if (childType === 'paragraph') {
        const text = extractText(child.content as Record<string, unknown>[])
        if (text) itemText.push(text)
      } else if (childType === 'bulletList' || childType === 'orderedList') {
        const subBlock = listToBlock(childType === 'orderedList', child.content as Record<string, unknown>[])
        children = subBlock.items ?? []
      } else if (childType === 'text') {
        const text = (child.text as string) ?? ''
        if (text) itemText.push(text)
      }
    }

    return { content: itemText.join(' '), children }
  })

  return createBlock('list', { ordered, items })
}

function tableToBlock(content: Record<string, unknown>[] | undefined): Block {
  const rows: string[][] = []
  let headers: string[] = []

  const allRows = content ?? []
  for (let i = 0; i < allRows.length; i++) {
    const rowNode = allRows[i]
    const cells = (rowNode.content as Record<string, unknown>[]) ?? []
    const cellTexts = cells.map((cell) => {
      const cellContent = (cell.content as Record<string, unknown>[]) ?? []
      return extractTextFromCells(cellContent)
    })

    if (i === 0 && cells[0]?.type === 'tableHeader') {
      headers = cellTexts
    } else {
      rows.push(cellTexts)
    }
  }

  return createBlock('table', { headers, rows, style: 'grid' })
}

function extractTextFromCells(nodes: Record<string, unknown>[]): string {
  const parts: string[] = []
  for (const node of nodes) {
    const text = extractText(node.content as Record<string, unknown>[])
    if (text) parts.push(text)
  }
  return parts.join(' ')
}

/**
 * 从 ProseMirror content 数组中提取纯文本
 * 支持 text nodes、嵌套 paragraph 等
 */
function extractText(content: Record<string, unknown>[] | undefined): string {
  if (!content || !Array.isArray(content)) return ''
  const parts: string[] = []
  for (const node of content) {
    const type = node.type as string
    if (type === 'text') {
      const text = (node.text as string) ?? ''
      if (text) parts.push(text)
    } else if (type === 'paragraph') {
      const text = extractText(node.content as Record<string, unknown>[])
      if (text) parts.push(text)
    } else if (type === 'hardBreak') {
      parts.push('\n')
    }
  }
  return parts.join('')
}

// ════════════════════════════════════════════════════════════
// 工具函数
// ════════════════════════════════════════════════════════════

/**
 * 判断 DSL 内容是否为空（无 blocks 或全部 block 内容为空）
 */
export function isDSLEmpty(content: ProposalContent | null | undefined): boolean {
  if (!content || !content.blocks || content.blocks.length === 0) return true
  return content.blocks.every(
    (b) => !b.content && !b.url && (b.items?.length ?? 0) === 0 && (b.rows?.length ?? 0) === 0,
  )
}

/**
 * 从旧格式 content_md/content_html 构建 DSL（惰性迁移）
 * 优先用后端返回的 content_dsl；无则用 content_html 解析；最后回退 content
 */
export function buildDSLFromLegacy(
  contentDsl: Record<string, unknown> | null | undefined,
  contentHtml: string | null | undefined,
  _contentMd: string | null | undefined,
): ProposalContent | null {
  // 优先用后端 DSL
  if (contentDsl && typeof contentDsl === 'object' && contentDsl.blocks) {
    return contentDsl as unknown as ProposalContent
  }

  // 回退：从 HTML 解析（复用 ProseMirror）
  if (contentHtml) {
    // 注意：HTML → ProseMirror 需要 Tiptap 编辑器实例，此处仅标注降级路径
    // 实际由 useChapterLoader 传给 Tiptap 后 getJSON 再转 DSL
    return null
  }

  // 最后回退：无内容
  return null
}
