/**
 * 占位符扩展：基于官方 @tiptap/extension-placeholder，
 * 工厂函数支持按场景定制文案（如章节编辑页）。
 */
import { Placeholder as BasePlaceholder } from '@tiptap/extension-placeholder'

/** 默认占位文案 */
export const DEFAULT_PLACEHOLDER = '请输入内容...'

/** 创建占位符扩展（可传入定制文案） */
export const createPlaceholderExtension = (placeholder: string = DEFAULT_PLACEHOLDER) =>
  BasePlaceholder.configure({
    placeholder,
    showOnlyWhenEditable: true,
  })
