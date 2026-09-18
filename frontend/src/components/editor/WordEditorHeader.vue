<template>
  <!--
    顶栏：返回 + 章节信息 + 保存 + 导出/打印 + 视图切换 + 目录 + 面板开关 + AI 辅助。
    从 WordEditorPage 抽出的**结构组件**（N7）：输入全是父级已命名的响应式值与 handler，
    自身不含业务逻辑与编辑器耦合；配套 CSS（.word-page__header* / __chapter-title /
    __save-hint* / __view-toggle）随之下沉，避免父级 scoped 样式断链。
  -->
  <header class="word-page__header">
    <div class="word-page__header-left">
      <a-button
        size="small"
        aria-label="返回分工页"
        @click="emit('back')"
      >
        <template #icon>
          <ArrowLeftOutlined />
        </template>
        返回
      </a-button>
      <a-divider type="vertical" />
      <a-tag color="blue">
        {{ chapterNo }}
      </a-tag>
      <span class="word-page__chapter-title">{{ chapterTitle || '章节编辑' }}</span>
      <a-tag
        v-if="taskStatusText"
        :color="taskStatusColor"
      >
        {{ taskStatusText }}
      </a-tag>
      <a-tag
        v-if="isReadOnly"
        color="default"
      >
        只读模式
      </a-tag>
    </div>
    <div class="word-page__header-right">
      <!-- 任务状态操作按钮 -->
      <a-button
        v-if="canAccept"
        size="small"
        type="primary"
        :loading="accepting"
        @click="emit('accept')"
      >
        领取任务
      </a-button>
      <a-button
        v-if="canSubmit"
        size="small"
        type="primary"
        :loading="submittingTask"
        @click="emit('submit')"
      >
        提交审核
      </a-button>
      <a-divider
        v-if="canAccept || canSubmit"
        type="vertical"
      />
      <span
        v-if="!isReadOnly"
        class="word-page__save-hint"
        :class="`word-page__save-hint--${saveStatus}`"
      >
        {{ saveHint }}
      </span>
      <a-button
        v-if="!isReadOnly"
        size="small"
        type="primary"
        :loading="saveStatus === 'saving'"
        aria-label="保存章节内容"
        @click="emit('save')"
      >
        保存
      </a-button>
      <a-button
        size="small"
        aria-label="导出Word"
        @click="emit('export-word')"
      >
        <template #icon>
          <DownloadOutlined />
        </template>
        导出
      </a-button>
      <a-button
        size="small"
        aria-label="打印"
        @click="emit('print')"
      >
        <template #icon>
          <PrinterOutlined />
        </template>
        打印
      </a-button>
      <!-- 视图切换：连页编辑 / 分页预览（Word 式逐页观感，A4 切分展示） -->
      <a-radio-group
        :value="previewMode"
        size="small"
        button-style="solid"
        class="word-page__view-toggle"
        aria-label="视图切换"
        @update:value="onPreviewChange"
      >
        <a-radio-button :value="false">
          连页
        </a-radio-button>
        <a-radio-button :value="true">
          分页预览
        </a-radio-button>
      </a-radio-group>
      <a-dropdown>
        <a-button size="small" aria-label="目录">
          <template #icon>
            <UnorderedListOutlined />
          </template>
          目录
        </a-button>
        <template #overlay>
          <a-menu>
            <a-menu-item key="insert" @click="emit('insert-toc')">
              插入目录
            </a-menu-item>
            <a-menu-item key="update" @click="emit('update-toc')">
              更新目录
            </a-menu-item>
          </a-menu>
        </template>
      </a-dropdown>
      <a-button
        size="small"
        :type="propertiesVisible ? 'primary' : 'default'"
        aria-label="属性面板"
        @click="emit('toggle-properties')"
      >
        <template #icon>
          <SettingOutlined />
        </template>
        属性
      </a-button>
      <a-button
        size="small"
        :type="commentsVisible ? 'primary' : 'default'"
        aria-label="批注面板"
        @click="emit('toggle-comments')"
      >
        <template #icon>
          <CommentOutlined />
        </template>
        批注
      </a-button>
      <a-button
        size="small"
        :type="versionHistoryVisible ? 'primary' : 'default'"
        aria-label="版本历史"
        @click="emit('toggle-version-history')"
      >
        <template #icon>
          <HistoryOutlined />
        </template>
        版本
      </a-button>
      <a-dropdown>
        <a-button size="small" type="primary" :loading="aiLoading" aria-label="AI 辅助">
          <template #icon>
            <RobotOutlined />
          </template>
          AI 辅助
        </a-button>
        <template #overlay>
          <a-menu>
            <a-menu-item key="polish" @click="emit('ai-action', 'polish')">
              <template #icon><EditOutlined /></template>
              AI 润色（选中文字）
            </a-menu-item>
            <a-menu-item key="expand" @click="emit('ai-action', 'expand')">
              <template #icon><ExpandOutlined /></template>
              AI 扩写（选中文字）
            </a-menu-item>
            <a-menu-item key="condense" @click="emit('ai-action', 'condense')">
              <template #icon><CompressOutlined /></template>
              AI 缩写（选中文字）
            </a-menu-item>
            <a-menu-item key="translate" @click="emit('ai-action', 'translate')">
              <template #icon><TranslationOutlined /></template>
              AI 翻译（选中文字）
            </a-menu-item>
            <a-menu-divider />
            <a-menu-item key="autoFormat" @click="emit('auto-format')">
              <template #icon><BgColorsOutlined /></template>
              AI 自动排版
            </a-menu-item>
          </a-menu>
        </template>
      </a-dropdown>
    </div>
  </header>
</template>

<script setup lang="ts">
import {
  ArrowLeftOutlined,
  BgColorsOutlined,
  CommentOutlined,
  CompressOutlined,
  DownloadOutlined,
  EditOutlined,
  ExpandOutlined,
  HistoryOutlined,
  PrinterOutlined,
  RobotOutlined,
  SettingOutlined,
  TranslationOutlined,
  UnorderedListOutlined,
} from '@ant-design/icons-vue'

/** AI 辅助菜单动作（与 WordEditorPage.handleAiAction 的入参一致） */
export type AiAction = 'polish' | 'expand' | 'condense' | 'translate'

defineProps<{
  /** 章节号（如 1.1） */
  chapterNo: string
  /** 章节标题（空则显示「章节编辑」） */
  chapterTitle: string
  /** 任务状态文案（空则不显示标签） */
  taskStatusText: string
  /** 任务状态标签颜色 */
  taskStatusColor: string
  /** 只读模式（显示「只读模式」标签并隐藏保存/提交） */
  isReadOnly: boolean
  /** 可领取任务 */
  canAccept: boolean
  /** 领取中 */
  accepting: boolean
  /** 可提交审核 */
  canSubmit: boolean
  /** 提交中 */
  submittingTask: boolean
  /** 保存提示文案 */
  saveHint: string
  /** 保存状态（驱动 .word-page__save-hint--{status} 与保存按钮 loading） */
  saveStatus: string
  /** true = 分页预览；false = 连页编辑 */
  previewMode: boolean
  /** 右侧属性面板显隐 */
  propertiesVisible: boolean
  /** 批注面板显隐 */
  commentsVisible: boolean
  /** 版本历史面板显隐 */
  versionHistoryVisible: boolean
  /** AI 辅助处理中 */
  aiLoading: boolean
}>()

const emit = defineEmits<{
  (e: 'back'): void
  (e: 'accept'): void
  (e: 'submit'): void
  (e: 'save'): void
  (e: 'export-word'): void
  (e: 'print'): void
  (e: 'update:previewMode', value: boolean): void
  (e: 'insert-toc'): void
  (e: 'update-toc'): void
  (e: 'toggle-properties'): void
  (e: 'toggle-comments'): void
  (e: 'toggle-version-history'): void
  (e: 'ai-action', action: AiAction): void
  (e: 'auto-format'): void
}>()

/** a-radio-group 的 update:value 载荷为 string | number | boolean，此处只认布尔 */
const onPreviewChange = (v: unknown) => emit('update:previewMode', v === true)
</script>

<style scoped>
/* ========== 顶栏 ========== */
.word-page__header {
  flex: 0 0 auto;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 var(--space-4);
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-color);
}

.word-page__header-left,
.word-page__header-right {
  display: flex;
  align-items: center;
  gap: var(--space-2);
}

.word-page__chapter-title {
  font-size: var(--font-size-lg);
  font-weight: 600;
  color: var(--text-primary);
}

/* 保存状态提示 */
.word-page__save-hint {
  font-size: var(--font-size-xs);
  color: var(--text-tertiary);
}
.word-page__save-hint--saving {
  color: var(--color-primary);
}
.word-page__save-hint--saved {
  color: var(--color-success);
}
.word-page__save-hint--error {
  color: var(--color-error);
}

/* 视图切换控件：垂直居中对齐 header 内按钮 */
.word-page__view-toggle {
  margin-left: 4px;
}
.word-page__view-toggle :deep(.ant-radio-button-wrapper) {
  font-size: 12px;
  padding: 0 10px;
}
</style>
