<template>
  <!-- 反馈重写抽屉 -->
  <a-drawer
    v-model:open="feedbackDrawerOpen"
    title="反馈重写"
    placement="right"
    :width="440"
  >
    <a-form layout="vertical">
      <a-form-item label="目标章节">
        <a-tag color="blue">
          章节 {{ activeChapter }}
        </a-tag>
      </a-form-item>
      <a-form-item label="修改意见">
        <a-textarea
          v-model:value="feedbackComment"
          :rows="8"
          placeholder="描述需要修改的内容，例如：补充行业成功案例"
        />
        <div class="hint">
          意见将回派给章节负责人；无分工的章节由 AI 重写
        </div>
      </a-form-item>
    </a-form>
    <div class="drawer-footer">
      <a-button @click="feedbackDrawerOpen = false">
        取消
      </a-button>
      <a-button
        type="primary"
        :loading="submittingFeedback"
        @click="handleSubmitChapterFeedback"
      >
        提交重写
      </a-button>
    </div>
  </a-drawer>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { message } from 'ant-design-vue'
import { confirmReview } from '@/api'

const props = defineProps<{
  projectId: string
  activeChapter: string
}>()

const emit = defineEmits<{
  /** 意见回派给章节负责人（redispatch），无需轮询 */
  (e: 'submitted'): void
  /** 已触发 AI 章节重写，父组件启动轮询 */
  (e: 'rewrite'): void
}>()

const feedbackDrawerOpen = ref(false)
const feedbackComment = ref('')
const submittingFeedback = ref(false)

const open = () => { feedbackComment.value = ''; feedbackDrawerOpen.value = true }

const handleSubmitChapterFeedback = async () => {
  const comment = feedbackComment.value.trim()
  if (!comment) { message.warning('请填写修改意见'); return }
  if (!props.activeChapter) { message.warning('请先选择章节'); return }
  submittingFeedback.value = true
  try {
    const res = await confirmReview(props.projectId, {
      action: 'feedback',
      feedback: { [props.activeChapter]: comment },
    })
    if (res.data?.code !== 0) { message.error(res.data?.message || '提交修改意见失败'); return }
    if (res.data?.data?.next_phase === 'redispatch') {
      message.success('修改意见已回派给章节负责人，重编提交后复审')
      feedbackDrawerOpen.value = false
      emit('submitted')
      return
    }
    message.success('修改意见已提交，已触发章节重写')
    feedbackDrawerOpen.value = false
    emit('rewrite')
  } catch { message.error('提交修改意见失败') }
  finally { submittingFeedback.value = false }
}

defineExpose({ open })
</script>

<style scoped>
.hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-tertiary);
}

.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 8px;
}
</style>
