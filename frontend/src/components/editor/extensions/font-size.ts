/**
 * 字号扩展：在 TextStyle mark 上挂载 fontSize 属性（与官方 Color/FontFamily 同一模式）
 * 渲染为 <span style="font-size: …">，并提供中文字号 ↔ px 映射预设。
 */
import { Extension } from '@tiptap/core'

/** 字号选项（label 为中文字号名，value 为 CSS font-size 值） */
export interface FontSizeOption {
  label: string
  value: string
}

/** 中文字号 ↔ px 映射（公文排版常用字号；五号=10.5px、小七=9px 等） */
export const FONT_SIZE_OPTIONS: FontSizeOption[] = [
  { label: '初号', value: '42px' },
  { label: '小初', value: '36px' },
  { label: '一号', value: '26px' },
  { label: '小一', value: '24px' },
  { label: '二号', value: '22px' },
  { label: '小二', value: '18px' },
  { label: '三号', value: '16px' },
  { label: '小三', value: '15px' },
  { label: '四号', value: '14px' },
  { label: '小四', value: '12px' },
  { label: '五号', value: '10.5px' },
  { label: '小七', value: '9px' },
]

/* 命令类型扩展：保证 chain().setFontSize(...) 在 TS 严格模式下可推导 */
declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    fontSize: {
      /** 设置选区文字字号（CSS font-size 值，如 '16px'） */
      setFontSize: (fontSize: string) => ReturnType
      /** 清除选区文字字号 */
      unsetFontSize: () => ReturnType
    }
  }
}

export const FontSize = Extension.create({
  name: 'fontSize',

  addOptions() {
    return {
      types: ['textStyle'],
    }
  },

  addGlobalAttributes() {
    return [
      {
        types: this.options.types,
        attributes: {
          fontSize: {
            default: null,
            parseHTML: (element) => element.style.fontSize?.replace(/['"]+/g, '') || null,
            renderHTML: (attributes) => {
              if (!attributes.fontSize) {
                return {}
              }
              return {
                style: `font-size: ${attributes.fontSize}`,
              }
            },
          },
        },
      },
    ]
  },

  addCommands() {
    return {
      setFontSize:
        (fontSize) =>
        ({ chain }) =>
          chain().setMark('textStyle', { fontSize }).run(),
      unsetFontSize:
        () =>
        ({ chain }) =>
          chain().setMark('textStyle', { fontSize: null }).removeEmptyTextStyle().run(),
    }
  },
})
