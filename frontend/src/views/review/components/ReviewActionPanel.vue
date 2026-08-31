<template>
  <div class="review-action">
    <!-- 当前章节状态 -->
    <div class="review-action__section">
      <div class="review-action__section-title">
        当前章节状态
      </div>
      <div class="review-action__status">
        <a-tag
          :color="statusColor"
          class="review-action__status-tag"
        >
          {{ statusText }}
        </a-tag>
        <span v-if="submitter" class="review-action__submitter">
          提交人：{{ submitter }}
        </span>
      </div>
    </div>

    <!-- 审阅操作 -->
    <div class="review-action__section">
      <div class="review-action__section-title">
        审阅操作
      </div>
      <a-space direction="vertical" style="width: 100%" :size="8">
        <a-button
          type="primary"
          block
          :loading="approving"
          :disabled="polling || currentStatus === 'approved'"
          @click="$emit('approve')"
        >
          <template #icon>
            <CheckOutlined />
          </template>
          通过
        </a-button>
        <a-button
          danger
          block
          :disabled="polling || currentStatus === 'rejected'"
          @click="openRejectModal"
        >
          <template #icon>
            <CloseOutlined />
          </template>
          打回
        </a-button>
      </a-space>
    </div>

    <!-- 审阅意见 -->
    <div class="review-action__section">
      <div class="review-action__section-title">
        审阅意见
      </div>
      <a-textarea
        v-model:value="comment"
        :rows="4"
        placeholder="打回时请填写审阅意见，通过时可选填..."
        :maxlength="500"
        show-count
      />
    </div>

    <!-- 历史审阅意见 -->
    <div
      v-if="(historyComments?.length ?? 0) > 0"
      class="review-action__section"
    >
      <div class="review-action__section-title">
        历史意见
      </div>
      <div class="review-action__history">
        <div
          v-for="(item, index) in historyComments || []"
          :key="index"
          class="review-action__history-item"
        >
          <div class="review-action__history-header">
            <a-tag
              :color="item.action === 'approved' ? 'green' : 'orange'"
              class="review-action__history-tag"
            >
              {{ item.action === 'approved' ? '通过' : '打回' }}
            </a-tag>
            <span class="review-action__history-time">{{ item.time }}</span>
          </div>
          <div
            v-if="item.comment"
            class="review-action__history-comment"
          >
            {{ item.comment }}
          </div>
        </div>
      </div>
    </div>

    <!-- 打回确认弹窗 -->
    <a-modal
      v-model:open="rejectModalOpen"
      title="确认打回"
      :confirm-loading="approving"
      ok-text="确认打回"
      cancel-text="取消"
      @ok="handleReject"
    >
      <p>确定要将章节 <strong>{{ activeChapter }}</strong> 打回修改吗？</p>
      <p v-if="!comment.trim()" style="color: #ff4d4f">
        请先填写审阅意见
      </p>
      <p v-else class="review-action__reject-comment">
        审阅意见：{{ comment }}
      </p>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { CheckOutlined, CloseOutlined } from '@ant-design/icons-vue'

interface HistoryComment {
  action: 'approved' | 'rejected'
  comment: string
  time: string
}

const props = defineProps<{
  activeChapter: string
  currentStatus: string
  submitter: string
  approving: boolean
  polling: boolean
  historyComments?: HistoryComment[]
}>()

const emit = defineEmits<{
  (e: 'approve'): void
  (e: 'reject', comment: string): void
}>()

const comment = ref('')
const rejectModalOpen = ref(false)

const statusText = computed(() => {
  const map: Record<string, string> = {
    pending: '未审阅',
    approved: '已通过',
    rejected: '需修改',
  }
  return map[props.currentStatus] || '未审阅'
})

const statusColor = computed(() => {
  const map: Record<string, string> = {
    pending: 'default',
    approved: 'green',
    rejected: 'orange',
  }
  return map[props.currentStatus] || 'default'
})

const openRejectModal = () => {
  if (!comment.value.trim()) {
    comment.value = ''
  }
  rejectModalOpen.value = true
}

const handleReject = () => {
  if (!comment.value.trim()) return
  emit('reject', comment.value.trim())
  rejectModalOpen.value = false
}

/** 外部设置审阅意见（如加载历史意见后） */
const setComment = (val: string) => {
  comment.value = val
}

defineExpose({ setComment })
</script>

<style scoped>
.review-action {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 16px;
}

.review-action__section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.review-action__section-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary, #fff);
}

.review-action__status {
  display: flex;
  align-items: center;
  gap: 8px;
}

.review-action__status-tag {
  font-size: 12px;
}

.review-action__submitter {
  font-size: 12px;
  color: var(--text-secondary, #999);
}

.review-action__history {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 200px;
  overflow-y: auto;
}

.review-action__history-item {
  padding: 8px 12px;
  background: var(--bg-surface, #2a2a2a);
  border-radius: 6px;
  border-left: 3px solid var(--border-color, #444);
}

.review-action__history-item:has(.review-action__history-tag[color="green"]) {
  border-left-color: #52c41a;
}

.review-action__history-item:has(.review-action__history-tag[color="orange"]) {
  border-left-color: #fa8c16;
}

.review-action__history-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.review-action__history-tag {
  font-size: 10px;
  margin: 0;
}

.review-action__history-time {
  font-size: 11px;
  color: var(--text-tertiary, #666);
}

.review-action__history-comment {
  font-size: 12px;
  color: var(--text-secondary, #ccc);
  line-height: 1.5;
}

.review-action__reject-comment {
  color: var(--text-secondary, #ccc);
  font-size: 13px;
}
</style>
