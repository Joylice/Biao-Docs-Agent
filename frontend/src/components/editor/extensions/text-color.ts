/**
 * 文字颜色扩展：复用官方 @tiptap/extension-color（color 属性挂载在 textStyle mark 上）
 * 另提供色板预设供工具栏颜色弹层使用。
 */
import { Color } from '@tiptap/extension-color'

/** 工具栏文字色板预设（覆盖常用公文标注色） */
export const TEXT_COLOR_PRESETS: string[] = [
  '#1f2329',
  '#646a73',
  '#8f959e',
  '#f54a45',
  '#ff8800',
  '#fdc424',
  '#34c724',
  '#14cccc',
  '#337eff',
  '#7c4aff',
  '#e0399b',
]

export const TextColor = Color
