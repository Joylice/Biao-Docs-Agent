/**
 * 表格扩展集合：基于官方 @tiptap/extension-table 系列。
 * - TableExt：开启列宽可调（resizable）+ 表格节点可选（allowTableNodeSelection）
 * - TableExtRow：标准表行
 * - TableExtCell / TableExtHeader：在默认 colspan/rowspan/colwidth 基础上
 *   追加「单元格对齐（水平/垂直）+ 边框（样式/颜色/宽度）+ 底纹颜色」属性，
 *   各自渲染为内联样式，配合 Table 扩展的 setCellAttribute 命令使用。
 *
 * 说明：tiptap 的 mergeAttributes 会按 CSS 属性名合并多个属性返回的内联 style
 * （text-align / vertical-align / background-color / border-* 互不冲突），
 * 因此这些属性可各自独立 renderHTML。
 */
import Table from '@tiptap/extension-table'
import TableRow from '@tiptap/extension-table-row'
import TableCell from '@tiptap/extension-table-cell'
import TableHeader from '@tiptap/extension-table-header'
import type { Attribute } from '@tiptap/core'

export const TableExt = Table.configure({
  resizable: true,
  allowTableNodeSelection: true,
})

/** 标准表行（无需扩展） */
export const TableExtRow = TableRow

/**
 * 单元格样式属性定义：对齐 + 边框 + 底纹，均渲染为内联样式。
 * 用 `Attribute` 类型标注后，parseHTML/renderHTML 回调由 tiptap 注入参数类型。
 */
const cellStyleAttributes: Record<string, Attribute> = {
  textAlign: {
    default: null,
    parseHTML: (element) => element.style.textAlign || null,
    renderHTML: (attributes) =>
      attributes.textAlign ? { style: `text-align: ${attributes.textAlign}` } : {},
  },
  verticalAlign: {
    default: null,
    parseHTML: (element) => element.style.verticalAlign || null,
    renderHTML: (attributes) =>
      attributes.verticalAlign ? { style: `vertical-align: ${attributes.verticalAlign}` } : {},
  },
  backgroundColor: {
    default: null,
    parseHTML: (element) => element.style.backgroundColor || null,
    renderHTML: (attributes) =>
      attributes.backgroundColor ? { style: `background-color: ${attributes.backgroundColor}` } : {},
  },
  borderStyle: {
    default: null,
    parseHTML: (element) => element.style.borderStyle || null,
    renderHTML: (attributes) =>
      attributes.borderStyle ? { style: `border-style: ${attributes.borderStyle}` } : {},
  },
  borderColor: {
    default: null,
    parseHTML: (element) => element.style.borderColor || null,
    renderHTML: (attributes) =>
      attributes.borderColor ? { style: `border-color: ${attributes.borderColor}` } : {},
  },
  borderWidth: {
    default: null,
    parseHTML: (element) => element.style.borderWidth || null,
    renderHTML: (attributes) =>
      attributes.borderWidth ? { style: `border-width: ${attributes.borderWidth}` } : {},
  },
}

/** 扩展单元格：在默认属性基础上追加对齐/边框/底纹属性 */
export const TableExtCell = TableCell.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      ...cellStyleAttributes,
    }
  },
})

/** 扩展表头单元格：追加对齐/边框/底纹属性 */
export const TableExtHeader = TableHeader.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      ...cellStyleAttributes,
    }
  },
})
