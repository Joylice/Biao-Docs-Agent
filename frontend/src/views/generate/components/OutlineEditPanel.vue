<template>
  <!-- 大纲待确认编辑区 -->
  <a-card
    class="generate-view__outline-edit"
    title="大纲编辑"
  >
    <template #extra>
      <a-space>
        <a-tag color="orange">
          待确认
        </a-tag>
        <a-tag
          v-if="draftState !== 'idle'"
          :color="draftTagColor"
        >
          {{ draftStatusText }}
        </a-tag>
        <template v-if="canEditOutlineNow">
        <a-tooltip title="基于最新评分点重新生成大纲，将覆盖当前编辑内容">
          <a-popconfirm
            title="重新生成将覆盖当前大纲编辑内容，确认继续？"
            ok-text="重新生成"
            cancel-text="取消"
            :confirm-loading="regenerating"
            @confirm="emit('regenerate')"
          >
            <a-button
              size="small"
              :loading="regenerating"
            >
              <template #icon>
                <ReloadOutlined />
              </template>
              重新生成
            </a-button>
          </a-popconfirm>
        </a-tooltip>
        <a-button
          size="small"
          :loading="draftState === 'saving'"
          @click="saveDraftNow"
        >
          保存草稿
        </a-button>
        <a-button
          size="small"
          type="primary"
          :loading="generating"
          @click="emit('confirm')"
        >
          确认大纲
        </a-button>
        </template>
      </a-space>
    </template>
    <a-alert
      v-if="!canEditOutlineNow"
      type="info"
      show-icon
      message="等待项目负责人确认大纲"
      class="mb-4"
    />
    <a-alert
      type="info"
      show-icon
      message="标题编号按层级自动重算；可增删子节、调整顺序与层级；编辑内容自动保存草稿；Ctrl+Z 撤销 / Ctrl+Shift+Z 重做结构化操作"
      class="mb-4"
    />
    <OutlineTreeEditor
      :nodes="editedTree"
      :active-key="activeNodeKey"
      :readonly="!canEditOutlineNow"
      @select="onEditSelect"
      @add-child="handleAddChild"
      @remove="handleRemoveNode"
      @move="handleMoveNode"
      @promote="handlePromoteNode"
      @demote="handleDemoteNode"
      @update-title="handleUpdateTitle"
      @update-clauses="handleUpdateClauses"
    />
    <a-button
      v-if="canEditOutlineNow"
      type="dashed"
      block
      class="mt-4"
      @click="handleAddChapter"
    >
      <template #icon>
        <PlusOutlined />
      </template>
      添加章节
    </a-button>
  </a-card>

  <!-- 草稿恢复弹窗 -->
  <a-modal
    v-model:open="draftRestoreVisible"
    title="恢复编辑草稿"
    ok-text="恢复草稿"
    cancel-text="丢弃草稿"
    @ok="applyDraft"
    @cancel="discardDraft"
  >
    <p>检测到 {{ pendingDraftUpdatedAt }} 保存的未完成大纲编辑草稿，是否恢复继续编辑？</p>
  </a-modal>
</template>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons-vue'
import { saveOutlineDraft, deleteOutlineDraft, fetchOutlineDraft } from '@/api'
import { useHotkeys } from '@/composables/useHotkeys'
import OutlineTreeEditor from '@/components/outline/OutlineTreeEditor.vue'
import { useOutlineEdit } from '../composables/useOutlineEdit'
import { outlineToTree, treeToOutline } from '../utils/outlineTree'
import type { OutlineItem, OutlineDraft } from '@/types'

const props = defineProps<{
  outline: OutlineItem[]
  projectId: string
  generating: boolean
  canEditOutlineNow: boolean
  regenerating?: boolean
}>()

const emit = defineEmits<{
  /** 点击「确认大纲」，由父组件校验并启动生成 */
  (e: 'confirm'): void
  /** 点击「重新生成」，由父组件调用 regenerateOutline API */
  (e: 'regenerate'): void
}>()

const {
  outlineHistory,
  editedTree,
  activeNodeKey,
  handleAddChapter,
  handleAddChild,
  handleRemoveNode,
  handleMoveNode,
  handlePromoteNode,
  handleDemoteNode,
  handleUpdateTitle,
  handleUpdateClauses,
  onEditSelect,
  handleOutlineUndo,
  handleOutlineRedo,
} = useOutlineEdit()

/* 快捷键：焦点在输入控件内不触发（useHotkeys 默认行为），纯文本输入走浏览器原生撤销 */
useHotkeys([
  { combo: 'ctrl+z', handler: handleOutlineUndo },
  { combo: 'ctrl+shift+z', handler: handleOutlineRedo },
  { combo: 'ctrl+y', handler: handleOutlineRedo },
])

// 草稿状态
type DraftState = 'idle' | 'dirty' | 'saving' | 'saved' | 'error'
const draftState = ref<DraftState>('idle')
const draftRestoreVisible = ref(false)
const pendingDraft = ref<OutlineDraft | null>(null)
const pendingDraftUpdatedAt = ref('')
let suppressDraftWatch = false
let draftTimer: number | null = null
const DRAFT_DEBOUNCE_MS = 2000

const draftStatusText = computed(() => {
  const map: Record<DraftState, string> = {
    idle: '', dirty: '未保存', saving: '保存中', saved: '已自动保存', error: '保存失败',
  }
  return map[draftState.value]
})

const draftTagColor = computed(() => {
  const map: Record<DraftState, string> = {
    idle: 'default', dirty: 'warning', saving: 'processing', saved: 'green', error: 'red',
  }
  return map[draftState.value]
})

/* ---------------- 大纲 → 编辑树同步 ---------------- */
const syncTreeFromOutline = () => {
  suppressDraftWatch = true
  editedTree.value = outlineToTree(props.outline)
  activeNodeKey.value = editedTree.value[0]?.key ?? ''
  // 外部（后端）大纲同步：以新树为基线，清空撤销历史
  outlineHistory.reset(editedTree.value)
  nextTick(() => { suppressDraftWatch = false })
}

// immediate：面板可能在大纲已就绪后才挂载（v-if 晚于数据加载），首次即同步树
watch(() => props.outline, syncTreeFromOutline, { deep: true, immediate: true })

/* ---------------- 草稿保存 ---------------- */
const scheduleDraftSave = () => {
  if (!props.canEditOutlineNow) return
  if (draftTimer !== null) clearTimeout(draftTimer)
  draftState.value = 'dirty'
  draftTimer = window.setTimeout(saveDraftNow, DRAFT_DEBOUNCE_MS)
}

const saveDraftNow = async () => {
  if (draftTimer !== null) { clearTimeout(draftTimer); draftTimer = null }
  draftState.value = 'saving'
  try {
    await saveOutlineDraft(props.projectId, {
      outline: treeToOutline(editedTree.value),
      mounted_doc_ids: null,
      mounted_kb_ids: null,
    })
    draftState.value = 'saved'
  } catch { draftState.value = 'error' }
}

const clearDraft = async () => {
  try { await deleteOutlineDraft(props.projectId) } catch { /* 幂等 */ }
  draftState.value = 'idle'
}

const loadDraftIfAny = async () => {
  try {
    const res = await fetchOutlineDraft(props.projectId)
    const d = res.data?.data
    if (d?.outline?.length) {
      pendingDraft.value = d
      pendingDraftUpdatedAt.value = d.updated_at ? new Date(d.updated_at).toLocaleString('zh-CN') : ''
      draftRestoreVisible.value = true
    }
  } catch { /* 静默 */ }
}

const applyDraft = () => {
  const d = pendingDraft.value
  if (!d) return
  suppressDraftWatch = true
  editedTree.value = outlineToTree(d.outline)
  // 草稿恢复为新基线，清空撤销历史
  outlineHistory.reset(editedTree.value)
  nextTick(() => { suppressDraftWatch = false })
  draftRestoreVisible.value = false
  pendingDraft.value = null
  draftState.value = 'saved'
  message.success('已恢复编辑草稿')
}

const discardDraft = () => {
  draftRestoreVisible.value = false
  pendingDraft.value = null
  clearDraft()
}

watch(editedTree, () => { if (!suppressDraftWatch) scheduleDraftSave() }, { deep: true })

/**
 * 面板仅在 awaitingOutlineConfirm 时挂载，故原 [awaiting, canEdit] 双源 watch
 * 收敛为 canEdit 单源：挂载即 awaiting=true，等待 canEdit 由 false→true 时加载草稿。
 */
watch(
  () => props.canEditOutlineNow,
  (canEdit, prevCanEdit) => {
    if (canEdit && !prevCanEdit && !draftRestoreVisible.value) {
      loadDraftIfAny()
    }
    if (!canEdit && draftTimer !== null) { clearTimeout(draftTimer); draftTimer = null }
  },
)

// 挂载时权限已就绪则直接加载（对应原 watch 首次触发已满足双条件的情形）
if (props.canEditOutlineNow && !draftRestoreVisible.value) {
  loadDraftIfAny()
}

/** 供父组件读取当前编辑树（确认大纲校验 / 提交） */
const getTree = () => editedTree.value

defineExpose({ getTree, clearDraft })

onUnmounted(() => {
  if (draftTimer !== null) { clearTimeout(draftTimer); draftTimer = null }
})
</script>

<style scoped>
.generate-view__outline-edit {
  margin-bottom: 16px;
}
.mt-4 { margin-top: 16px; }
.mb-4 { margin-bottom: 16px; }
</style>
