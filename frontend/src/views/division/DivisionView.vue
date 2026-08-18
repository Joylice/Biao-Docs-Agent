<template>
  <div class="division">
    <PageContainer
      title="分工协作"
      subtitle="负责人分配章节并审核，成员领取编制并提交"
    >
      <LoadingSkeleton
        v-if="loading"
        :rows="5"
      />
      <ErrorState
        v-else-if="loadError"
        :description="loadError"
      >
        <template #action>
          <a-button
            type="primary"
            @click="fetchAll"
          >
            重试
          </a-button>
        </template>
      </ErrorState>
      <template v-else>
        <!-- 成员视角：我的任务 -->
        <a-card
          v-if="myTasks.length > 0"
          title="我的任务"
          class="mb-4"
        >
          <a-list
            :data-source="myTasks"
            item-layout="vertical"
          >
            <template #renderItem="{ item }">
              <a-list-item class="task-item">
                <div class="task-item__head">
                  <span class="task-item__title">
                    {{ item.chapter_no }} {{ item.title }}
                  </span>
                  <a-tag :color="statusMeta(item.status).color">
                    {{ statusMeta(item.status).text }}
                  </a-tag>
                </div>
                <a-alert
                  v-if="item.status === 'rejected' && item.review_comment"
                  type="error"
                  show-icon
                  class="task-item__comment"
                  :message="`打回意见：${item.review_comment}`"
                />
                <div class="task-item__actions">
                  <a-button
                    v-if="item.status === 'pending' || item.status === 'rejected'"
                    type="primary"
                    size="small"
                    :loading="acceptingId === item.id"
                    @click="handleAccept(item)"
                  >
                    {{ item.status === 'rejected' ? '重新领取' : '领取任务' }}
                  </a-button>
                  <template v-if="item.status === 'in_progress'">
                    <a-button
                      size="small"
                      @click="openEditor(item)"
                    >
                      编制内容
                    </a-button>
                    <a-popconfirm
                      title="提交后需等待负责人审核，确认提交？"
                      ok-text="提交"
                      cancel-text="取消"
                      @confirm="handleSubmit(item)"
                    >
                      <a-button
                        size="small"
                        type="primary"
                        :loading="submittingId === item.id"
                      >
                        提交审核
                      </a-button>
                    </a-popconfirm>
                  </template>
                  <span
                    v-if="item.status === 'submitted'"
                    class="task-item__hint"
                  >
                    已提交，等待负责人审核
                  </span>
                  <span
                    v-if="item.status === 'approved'"
                    class="task-item__hint"
                  >
                    审核已通过
                  </span>
                </div>
              </a-list-item>
            </template>
          </a-list>
        </a-card>

        <!-- 章节分工表（负责人可分配/审核，成员可视） -->
        <a-card title="章节分工">
          <template #extra>
            <a-space>
              <span
                v-if="wsError"
                class="division__ws-error"
              >{{ wsError }}</span>
              <a-button
                v-if="isOwner"
                type="primary"
                :disabled="changedCount === 0"
                :loading="assigning"
                @click="handleAssign"
              >
                {{ changedCount > 0 ? `推送分工（${changedCount} 章）` : '推送分工' }}
              </a-button>
            </a-space>
          </template>
          <a-empty
            v-if="chapterRows.length === 0"
            description="暂无大纲章节，请先在「方案生成」页确认大纲"
          />
          <a-table
            v-else
            :columns="columns"
            :data-source="chapterRows"
            :pagination="false"
            row-key="chapter_no"
            size="small"
          >
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'assignee'">
                <a-select
                  v-if="isOwner"
                  v-model:value="draftAssignees[record.chapter_no]"
                  :options="memberOptions"
                  placeholder="选择负责人"
                  allow-clear
                  show-search
                  :filter-option="filterMember"
                  style="width: 180px"
                />
                <span v-else>{{ record.assignee_name || '未分配' }}</span>
              </template>
              <template v-if="column.key === 'status'">
                <a-tag
                  v-if="record.status"
                  :color="statusMeta(record.status).color"
                >
                  {{ statusMeta(record.status).text }}
                </a-tag>
                <span v-else>—</span>
              </template>
              <template v-if="column.key === 'section_status'">
                <a-tag
                  v-if="record.section_status"
                  :color="sectionStatusColor(record.section_status)"
                >
                  {{ sectionStatusText(record.section_status) }}
                </a-tag>
                <span v-else>—</span>
              </template>
              <template v-if="column.key === 'action'">
                <a-button
                  v-if="isOwner && record.status === 'submitted'"
                  size="small"
                  type="primary"
                  @click="openReview(record)"
                >
                  审核
                </a-button>
                <span
                  v-else-if="record.review_comment && record.status === 'rejected'"
                  class="division__comment"
                  :title="record.review_comment"
                >
                  打回意见：{{ record.review_comment }}
                </span>
              </template>
            </template>
          </a-table>
        </a-card>
      </template>
    </PageContainer>

    <!-- 成员编制：章节编辑器 -->
    <a-modal
      v-model:open="editorOpen"
      :title="`编制章节 ${editingTask ? editingTask.chapter_no + ' ' + editingTask.title : ''}`"
      width="800px"
      :footer="null"
    >
      <div class="editor-toolbar">
        <a-button
          :loading="generatingDraft"
          @click="handleGenerateDraft"
        >
          生成初稿
        </a-button>
        <a-button
          type="primary"
          :loading="savingContent"
          @click="handleSaveContent"
        >
          保存内容
        </a-button>
        <span class="editor-toolbar__hint">保存后可继续编辑，完成后在任务卡片点「提交审核」</span>
      </div>
      <a-textarea
        v-model:value="editorContent"
        :rows="16"
        placeholder="章节正文（可先点「生成初稿」由 LLM 起草，再人工修改）"
      />
    </a-modal>

    <!-- 负责人审核：通过 / 打回 + 意见 -->
    <a-modal
      v-model:open="reviewOpen"
      title="章节审核"
      :footer="null"
    >
      <div
        v-if="reviewTarget"
        class="review-box"
      >
        <div class="review-box__title">
          {{ reviewTarget.chapter_no }} {{ reviewTarget.title }}
        </div>
        <a-textarea
          v-model:value="reviewComment"
          :rows="3"
          placeholder="审核意见（打回时建议填写）"
        />
        <div class="review-box__actions">
          <a-button
            danger
            :loading="reviewingAction === 'rejected'"
            @click="handleReview('rejected')"
          >
            打回
          </a-button>
          <a-button
            type="primary"
            :loading="reviewingAction === 'approved'"
            @click="handleReview('approved')"
          >
            通过
          </a-button>
        </div>
      </div>
    </a-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { message } from 'ant-design-vue'
import api from '@/api/client'
import PageContainer from '@/components/PageContainer.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import { currentUserId, fetchCurrentUserRole } from '@/stores/currentUser'

interface OutlineItem {
  chapter_no: string
  title: string
}

interface MemberItem {
  user_id: string
  email: string
  display_name: string
  is_owner: boolean
}

interface AssignmentItem {
  id: string
  chapter_no: string
  title: string
  assignee_id: string
  assignee_name: string
  status: string
  section_status: string | null
  review_comment: string | null
}

/** 分工表行：大纲章节 + 分工记录合并 */
interface ChapterRow {
  chapter_no: string
  title: string
  assignment_id: string
  assignee_id: string
  assignee_name: string
  status: string
  section_status: string | null
  review_comment: string | null
}

const route = useRoute()
const projectId = route.params.projectId as string

const loading = ref(false)
const loadError = ref('')
const isOwner = ref(false)
const members = ref<MemberItem[]>([])
const outline = ref<OutlineItem[]>([])
const assignments = ref<AssignmentItem[]>([])
const chapters = ref<Record<string, string>>({})

// 分配草稿：chapter_no → assignee_id（与已推送值比较得出待推送变更）
const draftAssignees = ref<Record<string, string | undefined>>({})
const assigning = ref(false)
const acceptingId = ref('')
const submittingId = ref('')

// 编制编辑器
const editorOpen = ref(false)
const editingTask = ref<AssignmentItem | null>(null)
const editorContent = ref('')
const generatingDraft = ref(false)
const savingContent = ref(false)

// 审核弹窗
const reviewOpen = ref(false)
const reviewTarget = ref<ChapterRow | null>(null)
const reviewComment = ref('')
const reviewingAction = ref('')

const wsError = ref('')
let ws: WebSocket | null = null
let reconnectTimer: number | null = null
let reconnectAttempts = 0

const STATUS_META: Record<string, { text: string; color: string }> = {
  pending: { text: '待领取', color: 'orange' },
  in_progress: { text: '编制中', color: 'blue' },
  submitted: { text: '待审核', color: 'purple' },
  approved: { text: '已通过', color: 'green' },
  rejected: { text: '已打回', color: 'red' },
}

const statusMeta = (status: string) => STATUS_META[status] || { text: status, color: 'default' }

const sectionStatusText = (status: string) =>
  ({ draft: '初稿', final: '正式' })[status] || status
const sectionStatusColor = (status: string) =>
  ({ draft: 'blue', final: 'green' })[status] || 'default'

const columns = [
  { title: '章节', dataIndex: 'chapter_no', key: 'chapter_no', width: 80 },
  { title: '标题', dataIndex: 'title', key: 'title' },
  { title: '负责人', key: 'assignee', width: 200 },
  { title: '状态', key: 'status', width: 100 },
  { title: '内容', key: 'section_status', width: 80 },
  { title: '操作', key: 'action', width: 220 },
]

/** 大纲章节 + 分工记录合并为表格行（未在大纲中的历史分工追加在末尾） */
const chapterRows = computed<ChapterRow[]>(() => {
  const byNo = new Map(assignments.value.map((a) => [a.chapter_no, a]))
  const rows: ChapterRow[] = outline.value.map((c) => {
    const a = byNo.get(c.chapter_no)
    return {
      chapter_no: c.chapter_no,
      title: c.title,
      assignment_id: a?.id || '',
      assignee_id: a?.assignee_id || '',
      assignee_name: a?.assignee_name || '',
      status: a?.status || '',
      section_status: a?.section_status ?? null,
      review_comment: a?.review_comment ?? null,
    }
  })
  const outlineNos = new Set(outline.value.map((c) => c.chapter_no))
  for (const a of assignments.value) {
    if (!outlineNos.has(a.chapter_no)) {
      rows.push({
        chapter_no: a.chapter_no,
        title: a.title,
        assignment_id: a.id,
        assignee_id: a.assignee_id,
        assignee_name: a.assignee_name,
        status: a.status,
        section_status: a.section_status,
        review_comment: a.review_comment,
      })
    }
  }
  return rows
})

/** 我的任务（成员视角）：当前用户名下的分工记录 */
const myTasks = computed(() =>
  assignments.value.filter((a) => a.assignee_id === currentUserId.value),
)

const memberOptions = computed(() =>
  members.value.map((m) => ({
    value: m.user_id,
    label: m.display_name ? `${m.display_name}（${m.email}）` : m.email,
  })),
)

const filterMember = (input: string, option: { label: string }) =>
  option.label.toLowerCase().includes(input.toLowerCase())

/** 待推送的变更条目：草稿与已推送值不一致且非空 */
const changedItems = computed(() =>
  chapterRows.value.filter((r) => {
    const next = draftAssignees.value[r.chapter_no]
    return !!next && next !== r.assignee_id
  }),
)
const changedCount = computed(() => changedItems.value.length)

const getErrorMessage = (err: unknown, fallback: string): string => {
  const body = (err as { response?: { data?: { message?: string } } })?.response?.data
  return body?.message || fallback
}

const fetchAssignments = async () => {
  const { data } = await api.get(`/projects/${projectId}/chapter-assignments`)
  if (data.code === 0) {
    assignments.value = data.data.items || []
    // 同步分配草稿基线（owner 下拉初始值）
    const draft: Record<string, string | undefined> = {}
    for (const a of assignments.value) draft[a.chapter_no] = a.assignee_id
    draftAssignees.value = draft
  }
}

const fetchAll = async () => {
  loading.value = true
  loadError.value = ''
  try {
    await fetchCurrentUserRole()
    const [projectRes, memberRes, statusRes] = await Promise.all([
      api.get(`/projects/${projectId}`),
      api.get(`/projects/${projectId}/members`),
      api.get(`/projects/${projectId}/workflow/status`),
    ])
    if (projectRes.data?.code === 0) {
      isOwner.value = projectRes.data.data.owner_id === currentUserId.value
    }
    if (memberRes.data?.code === 0) {
      members.value = memberRes.data.data.items || []
    }
    const wf = statusRes.data?.data
    outline.value = wf?.outline || []
    chapters.value = wf?.chapters || {}
    await fetchAssignments()
  } catch {
    loadError.value = '分工数据加载失败'
  } finally {
    loading.value = false
  }
}

/** 推送分工（仅 owner）：只提交变更条目，后端幂等 upsert 并推送 task_assigned */
const handleAssign = async () => {
  const items = changedItems.value.map((r) => ({
    chapter_no: r.chapter_no,
    title: r.title,
    assignee_id: draftAssignees.value[r.chapter_no],
  }))
  if (items.length === 0) return
  assigning.value = true
  try {
    const { data } = await api.post(`/projects/${projectId}/chapter-assignments`, items)
    if (data.code === 0) {
      assignments.value = data.data.items || []
      const draft: Record<string, string | undefined> = {}
      for (const a of assignments.value) draft[a.chapter_no] = a.assignee_id
      draftAssignees.value = draft
      message.success(`已推送 ${items.length} 个章节的分工任务`)
    } else {
      message.error(data.message || '分工推送失败')
    }
  } catch (err) {
    message.error(getErrorMessage(err, '分工推送失败'))
  } finally {
    assigning.value = false
  }
}

const handleAccept = async (task: AssignmentItem) => {
  acceptingId.value = task.id
  try {
    const { data } = await api.post(`/projects/${projectId}/chapter-assignments/${task.id}/accept`)
    if (data.code === 0) {
      message.success('任务已领取，开始编制吧')
      await fetchAssignments()
    } else {
      message.error(data.message || '领取失败')
    }
  } catch (err) {
    message.error(getErrorMessage(err, '领取失败'))
  } finally {
    acceptingId.value = ''
  }
}

const openEditor = (task: AssignmentItem) => {
  editingTask.value = task
  editorContent.value = chapters.value[task.chapter_no] || ''
  editorOpen.value = true
}

/** 生成初稿：复用 generate_chapter 链路（mock 模式确定性降级） */
const handleGenerateDraft = async () => {
  const task = editingTask.value
  if (!task) return
  generatingDraft.value = true
  try {
    const { data } = await api.post(`/projects/${projectId}/chapter-assignments/${task.id}/generate`)
    if (data.code === 0) {
      const content = data.data.content || ''
      editorContent.value = content
      chapters.value[task.chapter_no] = content
      message.success(`章节 ${task.chapter_no} 初稿已生成，请人工修改完善`)
    } else {
      message.error(data.message || '初稿生成失败')
    }
  } catch (err) {
    message.error(getErrorMessage(err, '初稿生成失败'))
  } finally {
    generatingDraft.value = false
  }
}

/** 保存编辑内容：PUT sections/{chapter_no}（章节级权限后端兜底，非 assignee 会 403） */
const handleSaveContent = async () => {
  const task = editingTask.value
  if (!task) return
  const content = editorContent.value.trim()
  if (!content) {
    message.warning('章节内容不能为空')
    return
  }
  savingContent.value = true
  try {
    const { data } = await api.put(`/projects/${projectId}/workflow/sections/${task.chapter_no}`, {
      content,
    })
    if (data.code === 0) {
      chapters.value[task.chapter_no] = content
      message.success(`章节 ${task.chapter_no} 内容已保存`)
    } else {
      message.error(data.message || '保存失败')
    }
  } catch (err) {
    message.error(getErrorMessage(err, '保存失败'))
  } finally {
    savingContent.value = false
  }
}

const handleSubmit = async (task: AssignmentItem) => {
  submittingId.value = task.id
  try {
    const { data } = await api.post(`/projects/${projectId}/chapter-assignments/${task.id}/submit`)
    if (data.code === 0) {
      message.success('已提交，等待负责人审核')
      editorOpen.value = false
      await fetchAssignments()
    } else {
      message.error(data.message || '提交失败')
    }
  } catch (err) {
    message.error(getErrorMessage(err, '提交失败'))
  } finally {
    submittingId.value = ''
  }
}

const openReview = (row: ChapterRow) => {
  reviewTarget.value = row
  reviewComment.value = ''
  reviewOpen.value = true
}

const handleReview = async (action: 'approved' | 'rejected') => {
  const target = reviewTarget.value
  if (!target) return
  if (action === 'rejected' && !reviewComment.value.trim()) {
    message.warning('打回时请填写审核意见')
    return
  }
  reviewingAction.value = action
  try {
    const { data } = await api.post(
      `/projects/${projectId}/chapter-assignments/${target.assignment_id}/review`,
      { action, comment: reviewComment.value.trim() },
    )
    if (data.code === 0) {
      message.success(action === 'approved' ? '已通过审核' : '已打回，成员可重新编制')
      reviewOpen.value = false
      await fetchAssignments()
    } else {
      message.error(data.message || '审核失败')
    }
  } catch (err) {
    message.error(getErrorMessage(err, '审核失败'))
  } finally {
    reviewingAction.value = ''
  }
}

/* ---------------- WebSocket：task_* 事件实时刷新分工列表 ---------------- */
const connectWebSocket = () => {
  const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const token = localStorage.getItem('access_token') || ''
  const wsUrl = `${protocol}://${window.location.host}/ws/${projectId}?token=${encodeURIComponent(token)}`
  ws = new WebSocket(wsUrl)
  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data)
      if (['task_assigned', 'task_submitted', 'task_reviewed'].includes(data.type)) {
        fetchAssignments()
      }
    } catch {
      // 非 JSON 消息忽略
    }
  }
  ws.onopen = () => {
    reconnectAttempts = 0
    wsError.value = ''
  }
  ws.onclose = () => {
    reconnectAttempts += 1
    if (reconnectAttempts <= 5) {
      wsError.value = '连接已断开，正在自动重连...'
      reconnectTimer = window.setTimeout(connectWebSocket, 3000)
    } else {
      wsError.value = '连接已断开，请刷新页面重试'
    }
  }
}

onMounted(() => {
  fetchAll()
  connectWebSocket()
})

onBeforeUnmount(() => {
  if (reconnectTimer) window.clearTimeout(reconnectTimer)
  reconnectAttempts = 999
  ws?.close()
})
</script>

<style scoped>
.division {
  max-width: 1200px;
}

.mb-4 {
  margin-bottom: 16px;
}

.division__ws-error {
  font-size: 12px;
  color: #c62828;
}

.division__comment {
  font-size: 12px;
  color: #c62828;
}

.task-item {
  display: block;
}

.task-item__head {
  display: flex;
  align-items: center;
  gap: 12px;
}

.task-item__title {
  font-weight: 600;
}

.task-item__comment {
  margin-top: 8px;
}

.task-item__actions {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}

.task-item__hint {
  font-size: 12px;
  color: var(--text-secondary, #999);
}

.editor-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.editor-toolbar__hint {
  font-size: 12px;
  color: var(--text-secondary, #999);
}

.review-box__title {
  font-weight: 600;
  margin-bottom: 12px;
}

.review-box__actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 12px;
}
</style>
