<template>
  <!-- 批注编辑弹窗 -->
  <a-modal
    v-model:open="annotationEditModalOpen"
    title="编辑批注"
    ok-text="保存"
    cancel-text="取消"
    :confirm-loading="updatingAnnotation"
    @ok="handleUpdateAnnotationConfirm"
  >
    <a-textarea
      v-model:value="editingAnnotationContent"
      :rows="4"
      :maxlength="2000"
    />
  </a-modal>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { message } from 'ant-design-vue'
import { updateChapterAnnotation } from '@/api'
import type { AnnotationItem } from '@/types'

const props = defineProps<{
  projectId: string
  /** 当前审阅章节（批注所属章节） */
  activeChapter: string
}>()

const emit = defineEmits<{
  /** 更新成功，父组件以 patch 合并本地批注列表 */
  (e: 'updated', annotationId: string, patch: Partial<AnnotationItem>): void
}>()

const annotationEditModalOpen = ref(false)
const editingAnnotationId = ref('')
const editingAnnotationContent = ref('')
const updatingAnnotation = ref(false)

const open = (item: AnnotationItem) => {
  editingAnnotationId.value = item.id
  editingAnnotationContent.value = item.content
  annotationEditModalOpen.value = true
}

const handleUpdateAnnotationConfirm = async () => {
  const content = editingAnnotationContent.value.trim()
  if (!content || !editingAnnotationId.value) return
  updatingAnnotation.value = true
  try {
    const res = await updateChapterAnnotation(props.projectId, props.activeChapter, editingAnnotationId.value, content)
    if (res.data?.code === 0) {
      annotationEditModalOpen.value = false
      emit('updated', editingAnnotationId.value, res.data.data)
      message.success('批注已更新')
    }
  } catch { message.error('批注更新失败') }
  finally { updatingAnnotation.value = false }
}

defineExpose({ open })
</script>
