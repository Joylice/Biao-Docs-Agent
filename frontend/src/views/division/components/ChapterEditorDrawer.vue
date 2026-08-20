<template>
  <a-drawer
    :open="visible"
    :title="drawerTitle"
    :width="720"
    @close="handleClose"
  >
    <div
      v-if="task"
      class="chapter-editor"
    >
      <!-- 章节信息头部 -->
      <div class="chapter-editor__header">
        <div class="chapter-editor__meta">
          <a-tag color="blue">
            {{ task.chapter_no }}
          </a-tag>
          <span class="chapter-editor__title">{{ task.title }}</span>
        </div>
        <a-tag :color="statusColor">
          {{ statusText }}
        </a-tag>
      </div>

      <!-- 操作工具栏 -->
      <div class="chapter-editor__toolbar">
        <a-space wrap>
          <a-button
            v-if="canAccept"
            type="primary"
            size="small"
            :loading="accepting"
            @click="handleAccept"
          >
            领取任务
          </a-button>
          <a-button
            v-if="canSubmit"
            type="primary"
            size="small"
            :loading="submitting"
            @click="handleSubmit"
          >
            提交审核
          </a-button>
          <a-button
            v-if="canApprove"
            size="small"
            :loading="approving"
            @click="handleApprove"
          >
            审核通过
          </a-button>
          <a-button
            v-if="canReject"
            danger
            size="small"
            @click="showRejectModal = true"
          >
            打回
          </a-button>
          <a-button
            size="small"
            :loading="saving"
            :class="{ 'chapter-editor__save--success': saveSuccess }"
            @click="handleSave"
          >
            <template #icon>
              <CheckOutlined v-if="saveSuccess" />
            </template>
            {{ saveSuccess ? '已保存' : '保存' }}
          </a-button>
        </a-space>
      </div>

      <!-- AI 辅助 -->
      <div class="chapter-editor__assist">
        <a-input
          v-model:value="assistPrompt"
          placeholder="输入 AI 辅助指令，如：补充技术架构说明、优化语言表达..."
          allow-clear
          @press-enter="handleAssist"
        >
          <template #addonAfter>
            <a-button
              type="primary"
              :loading="assisting"
              @click="handleAssist"
            >
              AI 辅助
            </a-button>
          </template>
        </a-input>
        <a-radio-group
          v-model:value="assistMode"
          size="small"
          class="chapter-editor__assist-mode"
        >
          <a-radio-button value="append">
            追加
          </a-radio-button>
          <a-radio-button value="overwrite">
            覆盖
          </a-radio-button>
        </a-radio-group>
      </div>

      <!-- 内容编辑器 -->
      <div class="chapter-editor__content">
        <a-textarea
          v-model:value="editorContent"
          :rows="20"
          placeholder="在此编辑章节内容..."
          :disabled="!canEdit"
          class="chapter-editor__textarea"
        />
      </div>

      <!-- 预览 -->
      <div
        v-if="mode === 'preview'"
        class="chapter-editor__preview"
      >
        <MarkdownRenderer
          :source="editorContent"
          :project-id="projectId"
        />
      </div>

      <!-- 模式切换 -->
      <div class="chapter-editor__mode-switch">
        <a-segmented
          v-model:value="mode"
          :options="modeOptions"
        />
      </div>
    </div>

    <!-- 打回原因弹窗 -->
    <a-modal
      v-model:open="showRejectModal"
      title="打回原因"
      ok-text="确认打回"
      cancel-text="取消"
      :confirm-loading="rejecting"
      @ok="handleReject"
    >
      <a-textarea
        v-model:value="rejectComment"
        :rows="4"
        placeholder="请输入打回原因..."
      />
    </a-modal>
  </a-drawer>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { message } from 'ant-design-vue'
import { CheckOutlined } from '@ant-design/icons-vue'
import type { AssignmentItem } from '@/types'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import api from '@/api/client'
import { currentUserId } from '@/stores/currentUser'
import { useHotkeys } from '@/composables/useHotkeys'
import { useSuccessButton } from '@/composables/useSuccessButton'

const props = defineProps<{
  visible: boolean
  task: AssignmentItem | null
  projectId: string
  isOwner: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'updated'): void
}>()

const editorContent = ref('')
const mode = ref<'edit' | 'preview'>('edit')
const modeOptions = [
  { label: '编辑', value: 'edit' },
  { label: '预览', value: 'preview' },
]

// 操作状态
const saving = ref(false)
const accepting = ref(false)
const submitting = ref(false)
const approving = ref(false)
const rejecting = ref(false)
const assisting = ref(false)

// 保存成功反馈：短暂切换 success 样式 + CheckOutlined 图标
const { isSuccess: saveSuccess, runWithSuccess } = useSuccessButton()

// AI 辅助
const assistPrompt = ref('')
const assistMode = ref<'append' | 'overwrite'>('append')

// 打回
const showRejectModal = ref(false)
const rejectComment = ref('')

const drawerTitle = computed(() => props.task ? `章节编辑：${props.task.chapter_no}` : '章节编辑')

const statusText = computed(() => {
  const map: Record<string, string> = {
    pending: '待领取',
    in_progress: '编制中',
    rejected: '被打回',
    submitted: '已提审',
    approved: '已通过',
  }
  return map[props.task?.status || ''] || props.task?.status || ''
})

const statusColor = computed(() => {
  const map: Record<string, string> = {
    pending: 'default',
    in_progress: 'processing',
    rejected: 'error',
    submitted: 'warning',
    approved: 'success',
  }
  return map[props.task?.status || ''] || 'default'
})

const isAssignee = computed(() => props.task?.assignee_id === currentUserId.value)

const canEdit = computed(() => {
  if (!props.task) return false
  if (props.isOwner) return true
  if (isAssignee.value && ['in_progress', 'rejected'].includes(props.task.status)) return true
  return false
})

const canAccept = computed(() => props.task?.status === 'pending' && !props.task.assignee_id)
const canSubmit = computed(() => canEdit.value && props.task?.status === 'in_progress')
const canApprove = computed(() => props.isOwner && props.task?.status === 'submitted')
const canReject = computed(() => props.isOwner && props.task?.status === 'submitted')

// 加载章节内容
watch(
  () => props.visible,
  async (visible) => {
    if (visible && props.task) {
      try {
        const { data } = await api.get(
          `/projects/${props.projectId}/chapters/${props.task.chapter_no}/content`,
        )
        editorContent.value = data.data?.content || ''
      } catch {
        editorContent.value = ''
      }
    }
  },
)

const handleClose = () => {
  emit('close')
}

const handleSave = async () => {
  const task = props.task
  if (!task) return
  saving.value = true
  const ok = await runWithSuccess(async () => {
    await api.put(`/projects/${props.projectId}/chapters/${task.chapter_no}/content`, {
      content: editorContent.value,
    })
  })
  saving.value = false
  if (ok) {
    message.success('保存成功')
    emit('updated')
  } else {
    message.error('保存失败')
  }
}

/* 快捷键：Ctrl+S 保存章节内容（输入框聚焦时同样生效）。
   a-drawer 默认支持 Esc 关闭（未禁用 keyboard），无需额外处理。 */
useHotkeys([
  {
    combo: 'ctrl+s',
    allowInInput: true,
    handler: () => {
      if (props.visible) void handleSave()
    },
  },
])

const handleAccept = async () => {
  if (!props.task) return
  accepting.value = true
  try {
    await api.post(`/projects/${props.projectId}/chapter-assignments/${props.task.id}/accept`)
    message.success('已领取任务')
    emit('updated')
  } catch {
    message.error('领取失败')
  } finally {
    accepting.value = false
  }
}

const handleSubmit = async () => {
  if (!props.task) return
  await handleSave()
  submitting.value = true
  try {
    await api.post(`/projects/${props.projectId}/chapter-assignments/${props.task.id}/submit`)
    message.success('已提交审核')
    emit('updated')
  } catch {
    message.error('提交失败')
  } finally {
    submitting.value = false
  }
}

const handleApprove = async () => {
  if (!props.task) return
  approving.value = true
  try {
    await api.post(`/projects/${props.projectId}/chapter-assignments/${props.task.id}/review`, {
      action: 'approved',
    })
    message.success('审核通过')
    emit('updated')
  } catch {
    message.error('操作失败')
  } finally {
    approving.value = false
  }
}

const handleReject = async () => {
  if (!props.task) return
  rejecting.value = true
  try {
    await api.post(`/projects/${props.projectId}/chapter-assignments/${props.task.id}/review`, {
      action: 'rejected',
      comment: rejectComment.value,
    })
    message.success('已打回')
    showRejectModal.value = false
    rejectComment.value = ''
    emit('updated')
  } catch {
    message.error('操作失败')
  } finally {
    rejecting.value = false
  }
}

const handleAssist = async () => {
  if (!props.task || !assistPrompt.value.trim()) return
  assisting.value = true
  try {
    const { data } = await api.post(`/projects/${props.projectId}/chapters/assist`, {
      chapter_no: props.task.chapter_no,
      prompt: assistPrompt.value,
      mode: assistMode.value,
    })
    const newContent = data.data?.content
    if (typeof newContent === 'string') {
      if (assistMode.value === 'append') {
        editorContent.value += '\n\n' + newContent
      } else {
        editorContent.value = newContent
      }
      message.success('AI 辅助完成')
    }
  } catch {
    message.error('AI 辅助失败')
  } finally {
    assisting.value = false
  }
}
</script>

<style scoped>
.chapter-editor {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.chapter-editor__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--border-color);
  margin-bottom: var(--space-3);
}

.chapter-editor__meta {
  display: flex;
  align-items: center;
  gap: 10px;
}

.chapter-editor__title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.chapter-editor__toolbar {
  margin-bottom: var(--space-3);
}

/* 保存成功短暂反馈：success 底色（双主题走 CSS 变量） */
.chapter-editor__save--success {
  background: var(--color-success);
  border-color: var(--color-success);
  color: var(--text-inverse);
}

.chapter-editor__assist {
  margin-bottom: var(--space-3);
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.chapter-editor__assist-mode {
  align-self: flex-end;
}

.chapter-editor__content {
  flex: 1;
  min-height: 0;
}

.chapter-editor__textarea {
  height: 100%;
  font-family: var(--font-family-mono);
  font-size: 13px;
  line-height: 1.7;
}

.chapter-editor__preview {
  margin-top: var(--space-3);
  padding: var(--space-4);
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-md);
  max-height: 400px;
  overflow-y: auto;
}

.chapter-editor__mode-switch {
  margin-top: var(--space-3);
  display: flex;
  justify-content: center;
}
</style>
