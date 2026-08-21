<template>
  <!-- 手动快照弹窗 -->
  <a-modal
    v-model:open="snapshotModalOpen"
    title="手动创建版本快照"
    ok-text="创建快照"
    cancel-text="取消"
    :confirm-loading="snapshotting"
    @ok="handleCreateSnapshot"
  >
    <a-form layout="vertical">
      <a-form-item label="备注（可选）">
        <a-textarea
          v-model:value="snapshotNote"
          :rows="3"
          placeholder="例如：评审定稿版"
        />
      </a-form-item>
    </a-form>
  </a-modal>

  <!-- 归档弹窗 -->
  <a-modal
    v-model:open="archiveModalOpen"
    title="归档到公司知识库"
    ok-text="归档"
    cancel-text="取消"
    :confirm-loading="archiving"
    :ok-button-props="{ disabled: !archiveKbId }"
    @ok="handleArchive"
  >
    <a-form layout="vertical">
      <a-form-item label="目标知识库">
        <a-select
          v-model:value="archiveKbId"
          :options="companyBases"
          placeholder="选择公司级知识库"
        />
      </a-form-item>
      <div class="hint">
        归档后版本文档将入公司库分块向量化，供全公司方案生成检索
      </div>
    </a-form>
  </a-modal>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { message } from 'ant-design-vue'
import { createSnapshot, fetchKbBases, archiveVersionToKb } from '@/api'
import type { VersionItem } from '@/types'

interface KbBaseOption { value: string; label: string }

const props = defineProps<{
  projectId: string
}>()

const emit = defineEmits<{
  /** 快照创建成功，父组件刷新版本列表 */
  (e: 'snapshot-created'): void
}>()

// 版本库弹窗状态
const snapshotModalOpen = ref(false)
const snapshotNote = ref('')
const snapshotting = ref(false)
const archiveModalOpen = ref(false)
const archiving = ref(false)
const archiveKbId = ref<string | undefined>(undefined)
const archiveTarget = ref<VersionItem | null>(null)
const companyBases = ref<KbBaseOption[]>([])

const openSnapshotModal = () => { snapshotNote.value = ''; snapshotModalOpen.value = true }

const handleCreateSnapshot = async () => {
  snapshotting.value = true
  try {
    const res = await createSnapshot(props.projectId, snapshotNote.value.trim() || null)
    if (res.data?.code === 0) {
      message.success(`版本 v${res.data.data.version} 快照已创建`)
      snapshotModalOpen.value = false
      emit('snapshot-created')
    }
  } catch { message.error('快照创建失败') }
  finally { snapshotting.value = false }
}

const openArchiveModal = async (item: VersionItem) => {
  archiveTarget.value = item
  archiveKbId.value = undefined
  archiveModalOpen.value = true
  if (companyBases.value.length > 0) return
  try {
    const res = await fetchKbBases()
    if (res.data?.code === 0) {
      companyBases.value = (res.data.data.items || [])
        .filter((b: { scope: string }) => b.scope === 'company')
        .map((b: { id: string; name: string }) => ({ value: b.id, label: b.name }))
    }
  } catch { message.error('知识库列表加载失败') }
}

const handleArchive = async () => {
  if (!archiveTarget.value || !archiveKbId.value) return
  archiving.value = true
  try {
    const res = await archiveVersionToKb(props.projectId, archiveTarget.value.id, archiveKbId.value)
    if (res.data?.code === 0) { message.success(`已归档：${res.data.data.title}`); archiveModalOpen.value = false }
  } catch { message.error('归档失败') }
  finally { archiving.value = false }
}

defineExpose({ openSnapshotModal, openArchiveModal, snapshotting })
</script>

<style scoped>
.hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-tertiary);
}
</style>
