<template>
  <!-- 版本库 -->
  <ReviewVersionPanel
    :versions="versions"
    :is-owner="isOwner"
    :snapshotting="versionModalsRef?.snapshotting ?? false"
    :rolling-back-id="rollingBackId"
    @open-snapshot="versionModalsRef?.openSnapshotModal()"
    @download="handleDownloadVersion"
    @archive="(item) => versionModalsRef?.openArchiveModal(item)"
    @rollback="confirmRollback"
  />

  <!-- 手动快照 / 归档弹窗 -->
  <ReviewVersionModals
    ref="versionModalsRef"
    :project-id="projectId"
    @snapshot-created="fetchVersions"
  />
</template>

<script setup lang="ts">
import { ref, h } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { ExclamationCircleOutlined } from '@ant-design/icons-vue'
import {
  fetchProject,
  fetchVersions as fetchVersionsApi,
  downloadVersion,
  rollbackToVersion,
} from '@/api'
import type { VersionItem } from '@/types'
import { currentUserId, fetchCurrentUserRole } from '@/stores/currentUser'
import ReviewVersionPanel from './ReviewVersionPanel.vue'
import ReviewVersionModals from './ReviewVersionModals.vue'

const props = defineProps<{
  projectId: string
}>()

const emit = defineEmits<{
  /** 回滚成功：父组件刷新工作流状态（restored 为恢复章节数，由父组件统一提示） */
  (e: 'rolled-back', restored: number): void
}>()

const isOwner = ref(false)
const versions = ref<VersionItem[]>([])
const rollingBackId = ref('')
const versionModalsRef = ref<InstanceType<typeof ReviewVersionModals> | null>(null)

const fetchVersions = async () => {
  try {
    const res = await fetchVersionsApi(props.projectId)
    if (res.data?.code === 0) versions.value = res.data.data.items || []
  } catch { /* 不阻塞 */ }
}

const fetchOwnerFlag = async () => {
  try {
    await fetchCurrentUserRole()
    const res = await fetchProject(props.projectId)
    if (res.data?.code === 0) isOwner.value = res.data.data.owner_id === currentUserId.value
  } catch { isOwner.value = false }
}

/** 供父组件在 onMounted 中按原时序串行调用 */
const load = async () => {
  await fetchOwnerFlag()
  await fetchVersions()
}

const handleDownloadVersion = async (item: VersionItem, type: 'docx' | 'source') => {
  try {
    const res = await downloadVersion(props.projectId, item.id, type)
    if (res.data?.code === 0 && res.data.data.url) window.open(res.data.data.url, '_blank')
  } catch { message.error('下载链接生成失败') }
}

const handleRollback = async (item: VersionItem) => {
  rollingBackId.value = item.id
  try {
    const res = await rollbackToVersion(props.projectId, item.id)
    if (res.data?.code !== 0) { message.error(res.data?.message || '版本回滚失败'); return }
    const restored = res.data.data?.chapters_restored ?? 0
    await fetchVersions()
    emit('rolled-back', restored)
  } catch (err) {
    const status = (err as { response?: { status?: number } })?.response?.status
    message.error(status === 403 ? '仅项目负责人可回滚' : '版本回滚失败')
  } finally { rollingBackId.value = '' }
}

const confirmRollback = (item: VersionItem) => {
  Modal.confirm({
    title: '回滚版本',
    content: `将用版本 v${item.version} 的快照覆盖当前全部章节内容。确认回滚？`,
    okText: '确认回滚',
    cancelText: '取消',
    okButtonProps: { danger: true },
    icon: () => h(ExclamationCircleOutlined),
    onOk: () => handleRollback(item),
  })
}

defineExpose({ load, isOwner, versions })
</script>
