/**
 * Markdown ↔ HTML 双向转换器（纯函数）
 *
 * - markdownToHtml：基于 markdown-it（核心内置 GFM 表格/删除线；
 *   任务列表核心不支持，此处做轻量后处理转换为 checkbox 结构）
 * - htmlToMarkdown：基于 turndown，自定义规则保留表格/任务列表/删除线
 *
 * 说明：富文本样式（字体/颜色等）无法用 Markdown 表达，双向转换以
 * "结构信息不丢失"为目标；HTML 是编辑器样式的真实来源。
 */
import MarkdownIt from 'markdown-it'
import TurndownService from 'turndown'

/** 换行符常量（避免在正则字面量中书写转义序列） */
const NEWLINE = String.fromCharCode(10)

/**
 * markdown-it 单例：
 * - html:false 禁止原始 HTML 直通（防 XSS，与 MarkdownRenderer 保持一致）
 * - linkify 自动识别纯文本链接；核心默认支持 GFM 表格与 ~~删除线~~
 */
const markdownIt = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: false,
})

/** 匹配任务列表项标记：markdown-it 会把 `- [ ] foo` 渲染为 <li>[ ] foo</li> */
const TASK_ITEM_REGEX = /<li>\[([ xX])\]\s+/g

/**
 * Markdown → HTML
 * @param markdown Markdown 源文本（空串返回空串）
 * @returns 渲染后的 HTML 字符串（任务列表已转换为 checkbox 结构）
 */
export const markdownToHtml = (markdown: string): string => {
  if (!markdown || !markdown.trim()) return ''
  let html = markdownIt.render(markdown)

  /* 任务列表后处理：将 [ ] / [x] 文本标记替换为 checkbox input，
     结构与 Tiptap TaskItem 解析格式对齐（li.task-list-item + input） */
  html = html.replace(TASK_ITEM_REGEX, (_matched, checked: string) => {
    const checkedAttr = checked.trim() ? ' checked' : ''
    return `<li class="task-list-item"><input type="checkbox" class="task-list-item-checkbox" disabled${checkedAttr}> `
  })
  // 为包含任务项的列表补充语义 class，便于样式识别
  html = html.replace(/<ul>(?=\s*<li class="task-list-item">)/g, '<ul class="contains-task-list">')
  return html
}

/**
 * 创建配置好的 TurndownService 实例。
 * 每次调用新建实例，避免规则重复注册，保证 htmlToMarkdown 无副作用。
 */
const createTurndownService = (): TurndownService => {
  const service = new TurndownService({
    headingStyle: 'atx',
    codeBlockStyle: 'fenced',
    bulletListMarker: '-',
    emDelimiter: '*',
    strongDelimiter: '**',
  })

  // 删除线：<del>/<s>/<strike> → ~~text~~
  service.addRule('strikethrough', {
    filter: (node) => ['DEL', 'S', 'STRIKE'].includes(node.nodeName),
    replacement: (content) => `~~${content}~~`,
  })

  // checkbox input 本身丢弃（语义由父级任务列表项规则输出）
  service.addRule('checkbox-input', {
    filter: (node) => node.nodeName === 'INPUT',
    replacement: () => '',
  })

  // 任务列表项：<li><input type="checkbox">…</li> → - [ ] / - [x]
  service.addRule('task-list-item', {
    filter: (node) =>
      node.nodeName === 'LI' &&
      node instanceof HTMLElement &&
      !!node.querySelector(
        ':scope > input[type="checkbox"], :scope > label > input[type="checkbox"]',
      ),
    replacement: (content, node) => {
      const li = node as HTMLElement
      const input = li.querySelector('input[type="checkbox"]')
      const checked = !!input && input.hasAttribute('checked')
      // 压缩换行，保证单条任务项为单行 Markdown（续行缩进两空格）
      const text = content
        .replace(new RegExp(`^${NEWLINE}+`), '')
        .replace(new RegExp(`${NEWLINE}+$`), '')
        .replace(new RegExp(NEWLINE, 'gm'), `${NEWLINE}  `)
      return `${checked ? '- [x]' : '- [ ]'} ${text}`
    },
  })

  // 表格：HTMLTableElement → GFM 管道表格（单元格内容单独转 Markdown 并压平换行）
  service.addRule('gfm-table', {
    filter: (node) => node.nodeName === 'TABLE',
    replacement: (_content, node) => {
      const table = node as HTMLTableElement
      const rows = Array.from(table.rows)
      if (rows.length === 0) return ''

      const renderRow = (row: HTMLTableRowElement): string[] =>
        Array.from(row.cells).map((cell) => {
          const cellMd = service.turndown(cell.innerHTML)
          // 单元格必须是单行：换行压平为空格，竖线转义避免破坏表格结构
          return (
            cellMd
              .replace(new RegExp(`\\s*${NEWLINE}+\\s*`, 'g'), ' ')
              .trim()
              .replace(/\|/g, '\\|') || ' '
          )
        })

      const matrix = rows.map(renderRow)
      const colCount = Math.max(...matrix.map((cells) => cells.length))
      // 列数对齐：不同行列数不一致时补空列
      const normalized = matrix.map((cells) => {
        const next = [...cells]
        while (next.length < colCount) next.push(' ')
        return next
      })

      const [header = [], ...body] = normalized
      const separator = new Array<string>(colCount).fill('---')
      const lines = [
        `| ${header.join(' | ')} |`,
        `| ${separator.join(' | ')} |`,
        ...body.map((cells) => `| ${cells.join(' | ')} |`),
      ]
      return `${NEWLINE}${NEWLINE}${lines.join(NEWLINE)}${NEWLINE}${NEWLINE}`
    },
  })

  return service
}

/**
 * HTML → Markdown
 * @param html 编辑器导出的 HTML 字符串（空串返回空串）
 * @returns GFM Markdown 文本（表格/任务列表/删除线均保留）
 */
export const htmlToMarkdown = (html: string): string => {
  if (!html || !html.trim()) return ''
  // Tiptap 空文档为 '<p></p>'，转换后为空
  return createTurndownService().turndown(html).trim()
}