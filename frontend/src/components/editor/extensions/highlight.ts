/**
 * 高亮扩展：基于官方 @tiptap/extension-highlight，启用 multicolor 多彩高亮
 * （解析/渲染 background-color 内联样式），并提供色板预设。
 */
import { Highlight as BaseHighlight } from '@tiptap/extension-highlight'

/** 工具栏高亮色板预设（浅色系，保证深色文字可读性） */
export const HIGHLIGHT_COLOR_PRESETS: string[] = [
  '#fef2b1',
  '#fde2cc',
  '#fce6e6',
  '#e5f7e2',
  '#e0f5f5',
  '#e1eaff',
  '#ece5ff',
  '#f9e5f3',
  '#e8e8e8',
]

export const Highlight = BaseHighlight.configure({
  multicolor: true,
})
