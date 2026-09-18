<template>
  <Teleport to="body">
    <div
      v-if="menuVisible"
      class="ctx-menu"
      :class="{ 'ctx-menu--right': menuOnRight }"
      :style="{ left: `${menuX}px`, top: `${menuY}px` }"
    >
      <!-- 剪切 / 复制 / 粘贴 / 粘贴为纯文本 -->
      <div class="ctx-menu__section">
        <div
          class="ctx-menu__item"
          :class="{ 'ctx-menu__item--disabled': !hasSelection }"
          @click="handleCut"
        >
          <ScissorOutlined class="ctx-menu__icon" />
          <span>剪切</span>
        </div>
        <div
          class="ctx-menu__item"
          :class="{ 'ctx-menu__item--disabled': !hasSelection }"
          @click="handleCopy"
        >
          <CopyOutlined class="ctx-menu__icon" />
          <span>复制</span>
        </div>
        <div
          class="ctx-menu__item"
          @click="handlePaste"
        >
          <SnippetsOutlined class="ctx-menu__icon" />
          <span>粘贴</span>
        </div>
        <div
          class="ctx-menu__item"
          @click="handlePastePlain"
        >
          <SnippetsOutlined class="ctx-menu__icon" />
          <span>粘贴为纯文本</span>
        </div>
      </div>

      <div class="ctx-menu__divider" />

      <!-- 字体 / 字号 / 文字颜色（子菜单 hover 展开） -->
      <div class="ctx-menu__section">
        <div class="ctx-menu__item ctx-menu__item--has-sub">
          <FontSizeOutlined class="ctx-menu__icon" />
          <span>字体</span>
          <CaretRightOutlined class="ctx-menu__arrow" />
          <div class="ctx-menu__sub">
            <div
              v-for="opt in fontFamilyItems"
              :key="opt.value"
              class="ctx-menu__sub-item"
              :style="{ fontFamily: opt.value }"
              @click="handleFontFamily(opt.value)"
            >
              {{ opt.label }}
            </div>
          </div>
        </div>
        <div class="ctx-menu__item ctx-menu__item--has-sub">
          <FontSizeOutlined class="ctx-menu__icon" />
          <span>字号</span>
          <CaretRightOutlined class="ctx-menu__arrow" />
          <div class="ctx-menu__sub">
            <div
              v-for="opt in fontSizeItems"
              :key="opt.value"
              class="ctx-menu__sub-item"
              @click="handleFontSize(opt.value)"
            >
              {{ opt.label }}
            </div>
          </div>
        </div>
        <div class="ctx-menu__item ctx-menu__item--has-sub">
          <BgColorsOutlined class="ctx-menu__icon" />
          <span>文字颜色</span>
          <CaretRightOutlined class="ctx-menu__arrow" />
          <div class="ctx-menu__sub ctx-menu__sub--palette">
            <div class="ctx-menu__palette">
              <button
                v-for="color in TEXT_COLOR_PRESETS"
                :key="color"
                type="button"
                class="ctx-menu__swatch"
                :style="{ background: color }"
                :aria-label="`文字颜色 ${color}`"
                @click="handleTextColor(color)"
              />
              <button
                type="button"
                class="ctx-menu__swatch-reset"
                @click="run((chain) => chain.unsetColor())"
              >
                默认
              </button>
            </div>
          </div>
        </div>
      </div>

      <div class="ctx-menu__divider" />

      <!-- 段落对齐 + 行距 -->
      <div class="ctx-menu__section">
        <div class="ctx-menu__item ctx-menu__item--group">
          <span class="ctx-menu__group-label">对齐</span>
          <span class="ctx-menu__group-btns">
            <button
              type="button"
              class="ctx-menu__icon-btn"
              title="左对齐"
              @click="runAlign('left')"
            >
              <AlignLeftOutlined />
            </button>
            <button
              type="button"
              class="ctx-menu__icon-btn"
              title="居中"
              @click="runAlign('center')"
            >
              <AlignCenterOutlined />
            </button>
            <button
              type="button"
              class="ctx-menu__icon-btn"
              title="右对齐"
              @click="runAlign('right')"
            >
              <AlignRightOutlined />
            </button>
            <button
              type="button"
              class="ctx-menu__icon-btn"
              title="两端对齐"
              @click="runAlign('justify')"
            >
              <MenuOutlined />
            </button>
          </span>
        </div>
        <div class="ctx-menu__item ctx-menu__item--has-sub">
          <ColumnHeightOutlined class="ctx-menu__icon" />
          <span>行距</span>
          <CaretRightOutlined class="ctx-menu__arrow" />
          <div class="ctx-menu__sub">
            <div
              v-for="opt in lineHeightItems"
              :key="opt.value"
              class="ctx-menu__sub-item"
              @click="handleLineHeight(opt.value)"
            >
              {{ opt.label }}
            </div>
          </div>
        </div>
      </div>

      <div class="ctx-menu__divider" />

      <!-- 插入链接 / 图片 / 表格 / 查找 -->
      <div class="ctx-menu__section">
        <div
          class="ctx-menu__item"
          @click="handleInsertLink"
        >
          <LinkOutlined class="ctx-menu__icon" />
          <span>插入链接</span>
        </div>
        <div
          class="ctx-menu__item"
          @click="handleInsertImage"
        >
          <PictureOutlined class="ctx-menu__icon" />
          <span>插入图片</span>
        </div>
        <div
          class="ctx-menu__item"
          @click="handleInsertTable"
        >
          <TableOutlined class="ctx-menu__icon" />
          <span>插入表格</span>
        </div>
        <div
          class="ctx-menu__item"
          :class="{ 'ctx-menu__item--disabled': !hasSelection }"
          @click="handleFind"
        >
          <SearchOutlined class="ctx-menu__icon" />
          <span>查找选中文字</span>
        </div>
      </div>

      <div class="ctx-menu__divider" />

      <!-- AI 功能（2026-08-26 启用：润色/翻译/续写 → 父页面 assist-selection 选区处理） -->
      <div class="ctx-menu__section">
        <div
          class="ctx-menu__item"
          :class="{ 'ctx-menu__item--disabled': !canAiAction }"
          @click="handleAi('polish')"
        >
          <EditOutlined class="ctx-menu__icon" />
          <span>AI 润色</span>
        </div>
        <div
          class="ctx-menu__item"
          :class="{ 'ctx-menu__item--disabled': !canAiAction }"
          @click="handleAi('translate')"
        >
          <TranslationOutlined class="ctx-menu__icon" />
          <span>AI 翻译</span>
        </div>
        <div
          class="ctx-menu__item"
          :class="{ 'ctx-menu__item--disabled': !canAiAction }"
          @click="handleAi('expand')"
        >
          <RocketOutlined class="ctx-menu__icon" />
          <span>AI 续写</span>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
/**
 * WordEditorContextMenu：右键上下文菜单
 *
 * 实现委托 useEditorContextMenu（composable）：
 * - 在 editor.view.dom 上挂载 contextmenu 事件监听（watch editor 自动绑定/解绑）
 * - 菜单通过 Teleport + fixed 定位渲染，z-index 1050
 * - 字体/字号/颜色/行距使用 CSS :hover 子菜单（无需 JS 管理显隐）
 * - 剪切/复制/粘贴使用 Clipboard API + editor 命令
 * - 点击菜单项后关闭菜单；点击外部 / Esc 关闭菜单
 *
 * @param editor 编辑器实例
 * @emits insert-image 触发图片插入流程（父组件处理）
 * @emits insert-link 触发链接插入流程（父组件处理）
 * @emits find 将选中文本填入查找替换面板
 */
import type { Editor } from '@tiptap/core'
import {
  ScissorOutlined,
  CopyOutlined,
  SnippetsOutlined,
  FontSizeOutlined,
  BgColorsOutlined,
  CaretRightOutlined,
  AlignLeftOutlined,
  AlignCenterOutlined,
  AlignRightOutlined,
  MenuOutlined,
  ColumnHeightOutlined,
  LinkOutlined,
  PictureOutlined,
  TableOutlined,
  SearchOutlined,
  EditOutlined,
  TranslationOutlined,
  RocketOutlined,
} from '@ant-design/icons-vue'
import { useEditorContextMenu } from '@/composables/useEditorContextMenu'

const props = defineProps<{
  /** 编辑器实例 */
  editor: Editor | undefined
  /** 是否可编辑（只读/无权限时 AI 与编辑菜单保持禁用） */
  editable?: boolean
}>()

const emit = defineEmits<{
  (e: 'insert-image'): void
  (e: 'insert-link'): void
  (e: 'find', text: string): void
  /** AI 选区操作（父页面 WordEditorPage 处理；润色/翻译/续写） */
  (e: 'ai-action', action: 'polish' | 'translate' | 'expand'): void
}>()

const {
  menuVisible,
  menuOnRight,
  menuX,
  menuY,
  hasSelection,
  canAiAction,
  fontFamilyItems,
  fontSizeItems,
  lineHeightItems,
  TEXT_COLOR_PRESETS,
  run,
  runAlign,
  handleFontFamily,
  handleFontSize,
  handleTextColor,
  handleLineHeight,
  handleCut,
  handleCopy,
  handlePaste,
  handlePastePlain,
  handleInsertLink,
  handleInsertImage,
  handleInsertTable,
  handleFind,
  handleAi,
} = useEditorContextMenu({
  getEditor: () => props.editor,
  getEditable: () => props.editable,
  onInsertLink: () => emit('insert-link'),
  onInsertImage: () => emit('insert-image'),
  onFind: (text) => emit('find', text),
  onAiAction: (action) => emit('ai-action', action),
})
</script>

<style scoped>
/* 右键菜单容器 */
.ctx-menu {
  position: fixed;
  z-index: 1050;
  min-width: 200px;
  max-width: 260px;
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  padding: var(--space-1) 0;
  font-size: var(--font-size-sm);
  color: var(--text-primary);
  user-select: none;
}

/* 菜单分区 */
.ctx-menu__section {
  padding: 2px var(--space-2);
}

/* 分隔线 */
.ctx-menu__divider {
  height: 1px;
  margin: 4px 0;
  background: var(--border-color);
}

/* 菜单项 */
.ctx-menu__item {
  display: flex;
  align-items: center;
  gap: var(--space-2);
  padding: 5px var(--space-2);
  border-radius: var(--radius-xs);
  cursor: pointer;
  transition: background var(--transition-fast);
  position: relative;
}
.ctx-menu__item:hover {
  background: var(--bg-surface-hover);
}
.ctx-menu__item--disabled {
  color: var(--text-disabled);
  cursor: not-allowed;
}
.ctx-menu__item--disabled:hover {
  background: none;
}

.ctx-menu__icon {
  font-size: 14px;
  color: var(--text-secondary);
  flex-shrink: 0;
}
.ctx-menu__item--disabled .ctx-menu__icon {
  color: var(--text-disabled);
}

/* 子菜单箭头 */
.ctx-menu__arrow {
  margin-left: auto;
  font-size: 10px;
  color: var(--text-tertiary);
}

/* 子菜单（hover 展开） */
.ctx-menu__sub {
  display: none;
  position: absolute;
  left: 100%;
  top: 0;
  min-width: 140px;
  max-height: 320px;
  overflow-y: auto;
  background: var(--bg-elevated);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-lg);
  padding: var(--space-1) 0;
  z-index: 1;
}
/* 菜单在屏幕右侧时，子菜单向左展开 */
.ctx-menu--right .ctx-menu__sub {
  left: auto;
  right: 100%;
}
.ctx-menu__item--has-sub:hover .ctx-menu__sub {
  display: block;
}

/* 子菜单项 */
.ctx-menu__sub-item {
  padding: 5px var(--space-3);
  cursor: pointer;
  border-radius: var(--radius-xs);
  transition: background var(--transition-fast);
  white-space: nowrap;
}
.ctx-menu__sub-item:hover {
  background: var(--bg-surface-hover);
}

/* 色板子菜单 */
.ctx-menu__sub--palette {
  padding: var(--space-2);
}
.ctx-menu__palette {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--space-1);
}
.ctx-menu__swatch {
  width: 20px;
  height: 20px;
  border-radius: var(--radius-xs);
  border: 1px solid var(--border-color);
  cursor: pointer;
  padding: 0;
  transition: transform var(--transition-fast);
}
.ctx-menu__swatch:hover {
  transform: scale(1.15);
}
.ctx-menu__swatch-reset {
  grid-column: span 4;
  border: 1px dashed var(--border-color);
  border-radius: var(--radius-xs);
  background: var(--bg-surface);
  color: var(--text-secondary);
  font-size: var(--font-size-xs);
  padding: 3px 0;
  cursor: pointer;
}
.ctx-menu__swatch-reset:hover {
  color: var(--color-primary);
  border-color: var(--color-primary);
}

/* 对齐按钮组 */
.ctx-menu__item--group {
  cursor: default;
}
.ctx-menu__item--group:hover {
  background: none;
}
.ctx-menu__group-label {
  color: var(--text-secondary);
  flex-shrink: 0;
}
.ctx-menu__group-btns {
  display: flex;
  align-items: center;
  gap: 2px;
  margin-left: auto;
}
.ctx-menu__icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  background: none;
  cursor: pointer;
  border-radius: var(--radius-xs);
  color: var(--text-secondary);
  font-size: 13px;
  transition: background var(--transition-fast), color var(--transition-fast);
}
.ctx-menu__icon-btn:hover {
  background: var(--bg-surface-hover);
  color: var(--text-primary);
}

/* 深色模式微调 */
[data-theme='dark'] .ctx-menu {
  box-shadow: var(--shadow-deep);
}
</style>
