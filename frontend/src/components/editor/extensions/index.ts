/**
 * 编辑器扩展集合：统一导出 createEditorExtensions()
 * 含：StarterKit、下划线、字体/字号/行高/颜色/高亮、对齐、任务列表、
 * 图片/链接、占位符、字数统计，以及自实现的缩进扩展（text-indent 步进 2em）。
 */
import StarterKit from '@tiptap/starter-kit'
import Underline from '@tiptap/extension-underline'
import TextStyle from '@tiptap/extension-text-style'
import TextAlign from '@tiptap/extension-text-align'
import Image from '@tiptap/extension-image'
import Link from '@tiptap/extension-link'
import CharacterCount from '@tiptap/extension-character-count'
import TaskList from '@tiptap/extension-task-list'
import TaskItem from '@tiptap/extension-task-item'
import { Extension } from '@tiptap/core'
import { FontFamily } from './font-family'
import { FontSize } from './font-size'
import { LineHeight } from './line-height'
import { TextColor } from './text-color'
import { Highlight } from './highlight'
import { createPlaceholderExtension } from './placeholder'

/* ---------------- 缩进扩展（text-indent） ---------------- */

/** 缩进步进值（em），对齐 Word 首行缩进习惯 */
const INDENT_STEP_EM = 2
/** 缩进上限（em），防止无限缩进 */
const INDENT_MAX_EM = 8

/* 命令类型扩展 */
declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    indent: {
      /** 增加当前段落/标题首行缩进（步进 2em） */
      increaseIndent: () => ReturnType
      /** 减少当前段落/标题首行缩进（步进 2em） */
      decreaseIndent: () => ReturnType
    }
  }
}

/** 解析 text-indent 属性值为 em 数值（非法/空值视为 0） */
const parseIndentEm = (value: unknown): number => {
  if (typeof value !== 'string' || !value) return 0
  const num = parseFloat(value)
  return Number.isFinite(num) ? num : 0
}

/**
 * 缩进扩展：paragraph/heading 节点挂载 textIndent 属性，
 * 渲染为 style="text-indent: …em"；命令以 2em 步进增减、范围 [0, 8]em。
 */
const Indent = Extension.create({
  name: 'indent',

  addGlobalAttributes() {
    return [
      {
        types: ['paragraph', 'heading'],
        attributes: {
          textIndent: {
            default: null,
            parseHTML: (element) => element.style.textIndent || null,
            renderHTML: (attributes) => {
              if (!attributes.textIndent) {
                return {}
              }
              return {
                style: `text-indent: ${attributes.textIndent}`,
              }
            },
          },
        },
      },
    ]
  },

  addCommands() {
    /** 按 delta（em）调整光标所在段落/标题的首行缩进 */
    const changeIndent =
      (deltaEm: number) =>
      ({ state, commands }: { state: { selection: { $from: { parent: { type: { name: string }; attrs: Record<string, unknown> } } } }; commands: { updateAttributes: (type: string, attrs: Record<string, unknown>) => boolean } }) => {
        const parent = state.selection.$from.parent
        const type = parent.type.name
        if (type !== 'paragraph' && type !== 'heading') return false
        const current = parseIndentEm(parent.attrs.textIndent)
        const next = Math.min(Math.max(current + deltaEm, 0), INDENT_MAX_EM)
        if (next === current) return false
        // 缩进归零时置 null，移除内联样式
        return commands.updateAttributes(type, { textIndent: next === 0 ? null : `${next}em` })
      }

    return {
      increaseIndent: () => changeIndent(INDENT_STEP_EM),
      decreaseIndent: () => changeIndent(-INDENT_STEP_EM),
    }
  },
})

/* ---------------- 扩展集合入口 ---------------- */

export interface EditorExtensionOptions {
  /** 占位符文案 */
  placeholder?: string
}

/**
 * 创建 WordEditor 使用的扩展集合。
 * 说明：StarterKit 提供的 bold/italic/strike/heading/列表/引用/history 等
 * 与自定义扩展无功能重叠，整体保留；富文本样式类能力由下方自定义扩展承担。
 */
export const createEditorExtensions = (options: EditorExtensionOptions = {}) => [
  StarterKit.configure({
    heading: { levels: [1, 2, 3, 4] },
  }),
  Underline,
  // textStyle mark：字体/字号/文字色的样式载体
  TextStyle,
  FontFamily,
  FontSize,
  TextColor,
  Highlight,
  LineHeight,
  Indent,
  TextAlign.configure({ types: ['heading', 'paragraph'] }),
  TaskList,
  TaskItem.configure({ nested: true }),
  Image,
  Link.configure({
    openOnClick: false,
    autolink: true,
    HTMLAttributes: { rel: 'noopener noreferrer' },
  }),
  CharacterCount,
  createPlaceholderExtension(options.placeholder),
]
