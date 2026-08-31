<template>
  <a-space
    wrap
    :size="2"
    class="word-toolbar__group"
  >
    <!-- 表格 -->
    <a-popover
      trigger="click"
      placement="bottom"
      overlay-class-name="word-toolbar-popover"
    >
      <template #content>
        <div class="word-toolbar__table-picker">
          <span class="word-toolbar__picker-label">行</span>
          <a-input-number
            v-model:value="tableRows"
            :min="1"
            :max="20"
            size="small"
            style="width: 64px"
          />
          <span class="word-toolbar__picker-label">列</span>
          <a-input-number
            v-model:value="tableCols"
            :min="1"
            :max="20"
            size="small"
            style="width: 64px"
          />
          <a-button
            size="small"
            type="primary"
            @click="handleInsertTable"
          >
            插入
          </a-button>
        </div>
      </template>
      <a-tooltip title="插入表格">
        <a-button
          size="small"
          type="text"
          aria-label="插入表格"
        >
          <template #icon>
            <TableOutlined />
          </template>
          表格
        </a-button>
      </a-tooltip>
    </a-popover>

    <!-- 图片 -->
    <a-tooltip :title="uploadImage ? '插入图片' : '需要传入 uploadImage 属性'">
      <a-button
        size="small"
        type="text"
        :disabled="!uploadImage"
        aria-label="插入图片"
        @click="triggerImageUpload"
      >
        <template #icon>
          <PictureOutlined />
        </template>
        图片
      </a-button>
    </a-tooltip>
    <input
      ref="imageInputRef"
      type="file"
      accept="image/*"
      class="word-toolbar__file-input"
      @change="handleImageSelect"
    >

    <!-- 链接 -->
    <a-popover
      trigger="click"
      placement="bottom"
      overlay-class-name="word-toolbar-popover"
    >
      <template #content>
        <div class="word-toolbar__link-input">
          <a-input
            v-model:value="linkUrl"
            size="small"
            placeholder="https://"
            style="width: 200px"
            @keydown.enter.prevent="handleInsertLink"
          />
          <a-button
            size="small"
            type="primary"
            @click="handleInsertLink"
          >
            插入
          </a-button>
        </div>
      </template>
      <a-tooltip title="插入链接">
        <a-button
          size="small"
          type="text"
          aria-label="插入链接"
        >
          <template #icon>
            <LinkOutlined />
          </template>
          链接
        </a-button>
      </a-tooltip>
    </a-popover>

    <a-divider type="vertical" />

    <!-- 分页符 -->
    <a-tooltip title="插入分页符 (Ctrl+Enter)">
      <a-button
        size="small"
        type="text"
        aria-label="分页符"
        @click="run((chain) => chain.setPageBreak())"
      >
        <template #icon>
          <ColumnHeightOutlined />
        </template>
        分页符
      </a-button>
    </a-tooltip>

    <a-divider type="vertical" />

    <!-- 符号（P2） -->
    <a-tooltip title="P2 实现">
      <a-button
        size="small"
        type="text"
        disabled
        aria-label="符号"
      >
        <template #icon>
          <FontSizeOutlined />
        </template>
        符号
      </a-button>
    </a-tooltip>

    <!-- 页眉页脚（导出 Word/打印时自动生成，编辑态暂不开放） -->
    <a-tooltip title="导出 Word / 打印时自动生成页眉页脚">
      <a-button
        size="small"
        type="text"
        disabled
        aria-label="页眉页脚"
      >
        <template #icon>
          <LayoutOutlined />
        </template>
        页眉页脚
      </a-button>
    </a-tooltip>

    <!-- 批注（P3 已集成：打开右侧批注面板） -->
    <a-tooltip title="批注">
      <a-button
        size="small"
        type="text"
        aria-label="批注"
        @click="emit('openComments')"
      >
        <template #icon>
          <CommentOutlined />
        </template>
        批注
      </a-button>
    </a-tooltip>
  </a-space>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { Editor } from '@tiptap/core'
import {
  TableOutlined,
  PictureOutlined,
  LinkOutlined,
  ColumnHeightOutlined,
  FontSizeOutlined,
  LayoutOutlined,
  CommentOutlined,
} from '@ant-design/icons-vue'
import { useEditorCommands } from './useEditorCommands'

const props = defineProps<{
  editor: Editor | undefined
  projectId?: string
  uploadImage?: (file: File) => Promise<string>
}>()

const emit = defineEmits<{
  (e: 'openComments'): void
}>()

const { run } = useEditorCommands(() => props.editor)

/* 表格行列选择器 */
const tableRows = ref(3)
const tableCols = ref(3)

const handleInsertTable = () => {
  run((chain) => chain.insertTable({ rows: tableRows.value, cols: tableCols.value, withHeaderRow: true }))
}

/* 图片上传隐藏 input */
const imageInputRef = ref<HTMLInputElement | null>(null)

const triggerImageUpload = () => {
  imageInputRef.value?.click()
}

const handleImageSelect = async (e: Event) => {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file || !props.uploadImage) return
  try {
    const src = await props.uploadImage(file)
    run((chain) => chain.setImage({ src }))
  } catch {
    // 错误由 useImageUpload 处理
  }
  input.value = ''
}

/* 链接 URL 输入 */
const linkUrl = ref('')

const handleInsertLink = () => {
  if (linkUrl.value) {
    run((chain) => chain.setLink({ href: linkUrl.value }))
    linkUrl.value = ''
  }
}
</script>

<style scoped>
.word-toolbar__group {
  width: 100%;
}

.word-toolbar__file-input {
  display: none;
}

.word-toolbar__table-picker {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px;
}

.word-toolbar__picker-label {
  font-size: 12px;
  color: var(--text-secondary, #999);
}

.word-toolbar__link-input {
  display: flex;
  gap: 8px;
  padding: 8px;
}
</style>
