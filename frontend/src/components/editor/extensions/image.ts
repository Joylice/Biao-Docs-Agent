/**
 * 图片扩展：基于官方 @tiptap/extension-image，
 * 在默认 src/alt/title 基础上追加 width/height/float/边框（样式/颜色/宽度）属性，
 * 供 WordEditorImageToolbar 调整图片尺寸、浮动与边框使用。
 * 属性均渲染为内联样式；mergeAttributes 按 CSS 属性名合并，互不冲突。
 */
import Image from '@tiptap/extension-image'
import type { Attribute } from '@tiptap/core'

const imageStyleAttributes: Record<string, Attribute> = {
  width: {
    default: null,
    parseHTML: (element) => element.style.width || element.getAttribute('width') || null,
    renderHTML: (attributes) =>
      attributes.width ? { style: `width: ${attributes.width}` } : {},
  },
  height: {
    default: null,
    parseHTML: (element) => element.style.height || element.getAttribute('height') || null,
    renderHTML: (attributes) =>
      attributes.height ? { style: `height: ${attributes.height}` } : {},
  },
  float: {
    default: null,
    parseHTML: (element) => element.style.float || null,
    renderHTML: (attributes) =>
      attributes.float ? { style: `float: ${attributes.float}` } : {},
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

/** 扩展图片节点：追加尺寸/浮动/边框属性 */
export const ImageExt = Image.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      ...imageStyleAttributes,
    }
  },
})
