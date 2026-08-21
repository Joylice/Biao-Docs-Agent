/**
 * 字体扩展：基于官方 @tiptap/extension-font-family
 * 属性挂载在 textStyle mark 上（style="font-family: …"），
 * 并提供投标文档常用字体预设供工具栏下拉使用。
 */
import { FontFamily as BaseFontFamily } from '@tiptap/extension-font-family'

/** 字体选项（label 用于展示，value 为 CSS font-family 值） */
export interface FontFamilyOption {
  label: string
  value: string
}

/** 工具栏字体下拉预设：中文公文常用字体 + 常用西文字体 */
export const FONT_FAMILY_OPTIONS: FontFamilyOption[] = [
  { label: '宋体', value: 'SimSun, serif' },
  { label: '黑体', value: 'SimHei, sans-serif' },
  { label: '微软雅黑', value: '"Microsoft YaHei", sans-serif' },
  { label: 'Arial', value: 'Arial, sans-serif' },
  { label: 'Times New Roman', value: '"Times New Roman", serif' },
]

export const FontFamily = BaseFontFamily
