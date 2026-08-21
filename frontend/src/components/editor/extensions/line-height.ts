/**
 * 行高扩展：npm 上不存在官方 @tiptap/extension-line-height，
 * 此处以全局属性方式自实现——lineHeight 属性挂载在 paragraph/heading 节点上，
 * 渲染为 style="line-height: …"。
 */
import { Extension } from '@tiptap/core'

/** 工具栏行高下拉预设 */
export const LINE_HEIGHT_OPTIONS: number[] = [1, 1.15, 1.5, 2, 2.5, 3]

/* 命令类型扩展 */
declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    lineHeight: {
      /** 设置选区内段落/标题的行高 */
      setLineHeight: (lineHeight: number | string) => ReturnType
      /** 清除选区内段落/标题的行高 */
      unsetLineHeight: () => ReturnType
    }
  }
}

export const LineHeight = Extension.create({
  name: 'lineHeight',

  addOptions() {
    return {
      types: ['paragraph', 'heading'],
    }
  },

  addGlobalAttributes() {
    return [
      {
        types: this.options.types,
        attributes: {
          lineHeight: {
            default: null,
            parseHTML: (element) => element.style.lineHeight || null,
            renderHTML: (attributes) => {
              if (!attributes.lineHeight) {
                return {}
              }
              return {
                style: `line-height: ${attributes.lineHeight}`,
              }
            },
          },
        },
      },
    ]
  },

  addCommands() {
    return {
      setLineHeight:
        (lineHeight) =>
        ({ chain }) => {
          const value = String(lineHeight)
          /* updateAttributes 仅作用于选区内匹配类型的节点，不匹配即空操作，
             因此对 paragraph/heading 同时下发以覆盖两类节点 */
          return chain()
            .updateAttributes('paragraph', { lineHeight: value })
            .updateAttributes('heading', { lineHeight: value })
            .run()
        },
      unsetLineHeight:
        () =>
        ({ chain }) =>
          chain()
            .updateAttributes('paragraph', { lineHeight: null })
            .updateAttributes('heading', { lineHeight: null })
            .run(),
    }
  },
})
