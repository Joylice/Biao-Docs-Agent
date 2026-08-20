<template>
  <div class="division">
    <PageContainer
      title="方案生成"
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
                size="small"
                @click="expandAll"
              >
                全部展开
              </a-button>
              <a-button
                size="small"
                @click="collapseAll"
              >
                全部收起
              </a-button>
              <a-button
                v-if="isOwner"
                type="primary"
                :disabled="changedCount === 0"
                :loading="assigning"
                @click="handleAssign"
              >
                {{ changedCount > 0 ? `推送分工（${changedCount} 项）` : '推送分工' }}
              </a-button>
            </a-space>
          </template>
          <a-empty
            v-if="chapterRows.length === 0"
            description="暂无大纲章节，请先在「方案大纲生成」页确认大纲"
          />
          <a-table
            v-else
            v-model:expandedRowKeys="expandedKeys"
            :columns="columns"
            :data-source="chapterRows"
            :pagination="false"
            row-key="key"
            size="middle"
          >
            <template #bodyCell="{ column, record }">
              <!-- 阶段8：章行与子节行统一渲染，子节可分工（层级缩进由树形表格绘制） -->
              <template v-if="column.key === 'assignee'">
                <a-select
                  v-if="isOwner"
                  v-model:value="draftAssignees[record.chapter_no]"
                  :options="memberOptions"
                  :placeholder="record.kind === 'chapter' ? '选择负责人' : '分配子节'"
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
                  v-if="isOwner && record.status === 'submitted' && record.assignment_id"
                  size="small"
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

    <!-- 成员编制：章节编辑器（近全屏抽屉 + 编制工具栏） -->
    <a-drawer
      :open="editorOpen"
      :title="`编制章节 ${editingTask ? editingTask.chapter_no + ' ' + editingTask.title : ''}`"
      width="88%"
      :closable="!assisting"
      :mask-closable="!assisting"
      @close="closeEditor"
    >
      <div class="editor-toolbar">
        <a-button
          v-if="!assisting"
          @click="openAssist"
        >
          AI 生成
        </a-button>
        <a-button
          v-else
          danger
          :loading="stoppingAssist"
          @click="handleStopAssist"
        >
          暂停
        </a-button>
        <a-button
          :disabled="assisting"
          @click="manualEditing = !manualEditing"
        >
          {{ manualEditing ? '关闭编辑' : '人工编辑' }}
        </a-button>
        <a-button
          :disabled="assisting || !manualEditing"
          :loading="uploadingImage"
          @click="imageInputRef?.click()"
        >
          图片
        </a-button>
        <input
          ref="imageInputRef"
          type="file"
          accept="image/jpeg,image/png,image/gif,image/webp"
          style="display: none"
          @change="handleImageSelect"
        >
        <a-button
          type="primary"
          :loading="savingContent"
          :disabled="assisting"
          @click="handleSaveContent"
        >
          保存
        </a-button>
        <a-popconfirm
          v-if="editingTask && editingTask.status === 'in_progress'"
          title="提交后需等待负责人审核，确认提交？"
          ok-text="提交"
          cancel-text="取消"
          @confirm="handleSubmitFromEditor"
        >
          <a-button
            :loading="submittingId === editingTask.id"
            :disabled="assisting"
          >
            提审
          </a-button>
        </a-popconfirm>
        <a-button
          :disabled="assisting"
          @click="openAnnotations"
        >
          批注
        </a-button>
        <span class="editor-toolbar__hint">
          {{
            assisting
              ? 'AI 生成中，点「暂停」将保留已生成部分'
              : 'AI 生成基于挂载知识库 + 个人库检索，结果可追加或覆盖'
          }}
        </span>
      </div>
      <a-textarea
        v-if="manualEditing && !assisting"
        ref="editorTextareaRef"
        v-model:value="editorContent"
        class="editor-textarea"
        placeholder="章节正文（可先点「AI 生成」由知识库检索辅助起草，再人工修改）"
      />
      <div
        v-else
        class="editor-preview"
      >
        <MarkdownRenderer
          :source="previewContent"
          :project-id="projectId"
        />
        <div
          v-if="assisting"
          class="editor-preview__streaming"
        >
          生成中…可随时点「暂停」
        </div>
      </div>
    </a-drawer>

    <!-- 章节批注抽屉：留言列表（谁+时间+内容）+ 输入框 -->
    <a-drawer
      :open="annotOpen"
      title="章节批注"
      width="380px"
      @close="annotOpen = false"
    >
      <a-empty
        v-if="annotations.length === 0"
        description="暂无批注"
      />
      <a-list
        v-else
        :data-source="annotations"
        size="small"
      >
        <template #renderItem="{ item }">
          <a-list-item>
            <a-list-item-meta
              :description="item.content"
            >
              <template #title>
                <span>{{ item.created_by_name || '未知用户' }}</span>
                <span class="annot-time">{{ item.created_at?.replace('T', ' ').slice(0, 16) }}</span>
              </template>
            </a-list-item-meta>
          </a-list-item>
        </template>
      </a-list>
      <div class="annot-input">
        <a-textarea
          v-model:value="annotInput"
          :rows="3"
          placeholder="留下批注（章节负责人与项目负责人可写）"
        />
        <a-button
          type="primary"
          :loading="annotSending"
          :disabled="!annotInput.trim()"
          @click="handleAddAnnotation"
        >
          发送
        </a-button>
      </div>
    </a-drawer>

    <!-- AI 辅助生成：自定义提示词 + 追加/覆盖 -->
    <a-modal
      v-model:open="assistOpen"
      title="AI 辅助生成"
      :footer="null"
    >
      <div class="assist-box">
        <a-textarea
          v-model:value="assistPrompt"
          :rows="3"
          placeholder="自定义提示词（可选）：如重点覆盖的评分点、篇幅与风格要求等"
        />
        <a-radio-group
          v-model:value="assistMode"
          class="assist-box__mode"
        >
          <a-radio value="append">
            追加到正文末尾
          </a-radio>
          <a-radio value="overwrite">
            整章覆盖
          </a-radio>
        </a-radio-group>
        <div class="assist-box__actions">
          <a-button @click="assistOpen = false">
            取消
          </a-button>
          <a-button
            type="primary"
            @click="handleAssistGenerate"
          >
            开始生成
          </a-button>
        </div>
      </div>
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
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'
import { currentUserId, fetchCurrentUserRole } from '@/stores/currentUser'
import { usePermission } from '@/composables/usePermission'

/** 大纲子节：字符串（LLM 原始）或嵌套树（二次编辑产物），展示时拍平为标题 */
type OutlineSectionLike = string | { title: string; children?: OutlineSectionLike[] }

interface OutlineItem {
  chapter_no: string
  title: string
  sections?: OutlineSectionLike[]
}

interface MemberItem {
  user_id: string
  email: string
  display_name: string
  is_owner: boolean
}

/** 章节分工记录（树形接口：章级聚合行 id/assignee 为 null，子节分工在 children） */
interface AssignmentItem {
  id: string | null
  chapter_no: string
  title: string
  assignee_id: string | null
  assignee_name: string | null
  status: string
  section_status: string | null
  review_comment: string | null
  sections?: OutlineSectionLike[]
  children?: AssignmentItem[]
  total?: number
  approved_count?: number
}

/** 分工表行：大纲章节 + 分工记录合并（阶段8：树形层级，子节行可分工） */
interface ChapterRow {
  kind: 'chapter'
  key: string
  chapter_no: string
  title: string
  assignment_id: string
  assignee_id: string
  assignee_name: string
  status: string
  section_status: string | null
  review_comment: string | null
  children: SectionRow[]
}

/** 子节行（阶段8：层级编号 1.1/1.2，可分工） */
interface SectionRow {
  kind: 'section'
  key: string
  chapter_no: string
  title: string
  assignment_id: string
  assignee_id: string
  assignee_name: string
  status: string
  section_status: string | null
  review_comment: string | null
}

type DivisionRow = ChapterRow | SectionRow

interface AnnotationItem {
  id: string
  chapter_no: string
  content: string
  created_by: string
  created_by_name: string
  created_at: string | null
}

const route = useRoute()
const projectId = route.params.projectId as string

const loading = ref(false)
const loadError = ref('')
/** 项目 owner ID（项目详情返回，usePermission 比较当前用户） */
const projectOwnerId = ref('')
const { isProjectOwner } = usePermission()
/** 当前用户是否为项目所有者（决定分配/审核入口可见性） */
const isOwner = computed(() => isProjectOwner(projectOwnerId.value))
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
const manualEditing = ref(false)
const savingContent = ref(false)

// AI 辅助生成（可暂停，WS section_token source=assist 流式渲染）
const assistOpen = ref(false)
const assistPrompt = ref('')
const assistMode = ref<'append' | 'overwrite'>('append')
const assisting = ref(false)
const stoppingAssist = ref(false)
const streamDelta = ref('')

// 图片插入（上传 MinIO → Markdown 语法入正文，预览态渲染）
const uploadingImage = ref(false)
const imageInputRef = ref<HTMLInputElement | null>(null)
const editorTextareaRef = ref<unknown>(null)

// 章节批注抽屉
const annotOpen = ref(false)
const annotations = ref<AnnotationItem[]>([])
const annotInput = ref('')
const annotSending = ref(false)

/** 预览内容：生成中 = 现有正文 + 流式增量（覆盖模式仅显示增量） */
const previewContent = computed(() => {
  if (!assisting.value) return editorContent.value
  if (assistMode.value === 'overwrite') return streamDelta.value
  const base = editorContent.value.trim()
  return base ? `${base}\n\n${streamDelta.value}` : streamDelta.value
})

// 审核弹窗
const reviewOpen = ref(false)
const reviewTarget = ref<DivisionRow | null>(null)
const reviewComment = ref('')
const reviewingAction = ref('')

const wsError = ref('')
let ws: WebSocket | null = null
let reconnectTimer: number | null = null
let reconnectAttempts = 0

const STATUS_META: Record<string, { text: string; color: string }> = {
  pending: { text: '待领取', color: 'default' },
  in_progress: { text: '编制中', color: 'processing' },
  submitted: { text: '待审核', color: 'warning' },
  approved: { text: '已通过', color: 'success' },
  rejected: { text: '已打回', color: 'error' },
}

const statusMeta = (status: string) => STATUS_META[status] || { text: status, color: 'default' }

const sectionStatusText = (status: string) =>
  ({ draft: '初稿', final: '正式' })[status] || status
const sectionStatusColor = (status: string) =>
  ({ draft: 'processing', final: 'success' })[status] || 'default'

const columns = [
  { title: '章节', dataIndex: 'chapter_no', key: 'chapter_no', width: 100 },
  { title: '标题', dataIndex: 'title', key: 'title' },
  { title: '负责人', key: 'assignee', width: 200 },
  { title: '状态', key: 'status', width: 100 },
  { title: '内容', key: 'section_status', width: 80 },
  { title: '操作', key: 'action', width: 220 },
]

/** 大纲子节 → 标题扁平列表（兼容嵌套树形态，仅取标题展示） */
const sectionTitles = (sections?: OutlineSectionLike[]): string[] => {
  if (!Array.isArray(sections)) return []
  return sections.flatMap((s) =>
    typeof s === 'string' ? [s] : [s.title, ...sectionTitles(s.children)],
  )
}

/** 大纲章节 + 分工记录合并为树形表格行（阶段8：子节编号化为 children，可分工） */
const chapterRows = computed<ChapterRow[]>(() => {
  const byNo = new Map(assignments.value.map((a) => [a.chapter_no, a]))
  const rows: ChapterRow[] = []
  const pushed = new Set<string>()
  const makeSection = (no: string, title: string): SectionRow => {
    const a = byNo.get(no)
    return {
      kind: 'section',
      key: no,
      chapter_no: no,
      title,
      assignment_id: a?.id || '',
      assignee_id: a?.assignee_id || '',
      assignee_name: a?.assignee_name || '',
      status: a?.status || '',
      section_status: a?.section_status ?? null,
      review_comment: a?.review_comment ?? null,
    }
  }
  const pushChapter = (chapterNo: string, title: string, sectionNames: string[]) => {
    const a = byNo.get(chapterNo)
    // 大纲子节编号化（1.1/1.2…），取对应分工记录填充负责人/状态
    const children = sectionNames.map((s, idx) => makeSection(`${chapterNo}.${idx + 1}`, s))
    const covered = new Set(children.map((c) => c.chapter_no))
    // 追加未被大纲子节覆盖的子节级分工记录（编号超出大纲范围的历史分工）
    for (const item of assignments.value) {
      if (item.chapter_no.startsWith(`${chapterNo}.`) && !covered.has(item.chapter_no)) {
        children.push(makeSection(item.chapter_no, item.title))
      }
    }
    rows.push({
      kind: 'chapter',
      key: chapterNo,
      chapter_no: chapterNo,
      title,
      assignment_id: a?.id || '',
      assignee_id: a?.assignee_id || '',
      assignee_name: a?.assignee_name || '',
      status: a?.status || '',
      section_status: a?.section_status ?? null,
      review_comment: a?.review_comment ?? null,
      children,
    })
    pushed.add(chapterNo)
    children.forEach((c) => pushed.add(c.chapter_no))
  }
  for (const c of outline.value) {
    pushChapter(c.chapter_no, c.title, sectionTitles(byNo.get(c.chapter_no)?.sections ?? c.sections))
  }
  for (const a of assignments.value) {
    if (pushed.has(a.chapter_no)) continue
    // 子节级记录（编号含 '.'）若父章已展示，则已并入其 children，不重复提升为顶层
    if (a.chapter_no.includes('.') && pushed.has(a.chapter_no.split('.')[0])) continue
    pushChapter(a.chapter_no, a.title, sectionTitles(a.sections))
  }
  return rows
})

// 展开控制（阶段8）：默认展开一级章行，支持全部展开/收起
const expandedKeys = ref<string[]>([])
const expandAll = () => {
  expandedKeys.value = chapterRows.value.map((r) => r.key)
}
const collapseAll = () => {
  expandedKeys.value = []
}

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

/** 可分配行：章行 + 其子节行（阶段8：分工到二级） */
const assignableRows = computed<DivisionRow[]>(() =>
  chapterRows.value.flatMap((r) => [r, ...r.children]),
)

/** 待推送的变更条目：草稿与已推送值不一致且非空（章与子节均参与分配） */
const changedItems = computed(() =>
  assignableRows.value.filter((r) => {
    const next = draftAssignees.value[r.chapter_no]
    return !!next && next !== r.assignee_id
  }),
)
const changedCount = computed(() => changedItems.value.length)

const getErrorMessage = (err: unknown, fallback: string): string => {
  const body = (err as { response?: { data?: { message?: string } } })?.response?.data
  return body?.message || fallback
}

/** 分工树递归拍平：章行 + 子节 children（子节分工也纳入「我的任务」匹配） */
const flattenAssignments = (items: AssignmentItem[]): AssignmentItem[] =>
  items.flatMap((a) => [a, ...(a.children?.length ? flattenAssignments(a.children) : [])])

const fetchAssignments = async () => {
  const { data } = await api.get(`/projects/${projectId}/chapter-assignments`)
  if (data.code === 0) {
    // 树形接口：章行含子节 children，拍平后供任务匹配与表格行合并
    assignments.value = flattenAssignments(data.data.items || [])
    // 同步分配草稿基线（owner 下拉初始值）
    const draft: Record<string, string | undefined> = {}
    for (const a of assignments.value) draft[a.chapter_no] = a.assignee_id ?? undefined
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
      projectOwnerId.value = projectRes.data.data?.owner_id || ''
    }
    if (memberRes.data?.code === 0) {
      members.value = memberRes.data.data.items || []
    }
    const wf = statusRes.data?.data
    outline.value = wf?.outline || []
    chapters.value = wf?.chapters || {}
    await fetchAssignments()
    // 默认展开一级章行，二级子节按需展开
    expandedKeys.value = chapterRows.value.map((r) => r.key)
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
      // 响应同为树形结构，拍平保持与拉取路径一致
      assignments.value = flattenAssignments(data.data.items || [])
      const draft: Record<string, string | undefined> = {}
      for (const a of assignments.value) draft[a.chapter_no] = a.assignee_id ?? undefined
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
  if (!task.id) return
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
  manualEditing.value = true
  streamDelta.value = ''
  editorOpen.value = true
}

const closeEditor = () => {
  editorOpen.value = false
  editingTask.value = null
  manualEditing.value = false
  streamDelta.value = ''
}

const openAssist = () => {
  assistPrompt.value = ''
  assistMode.value = editorContent.value.trim() ? 'append' : 'overwrite'
  assistOpen.value = true
}

/** AI 辅助生成：知识库检索 + 章节上下文 + 自定义提示词，流式经 WS 推送 */
const handleAssistGenerate = async () => {
  const task = editingTask.value
  if (!task) return
  assistOpen.value = false
  assisting.value = true
  streamDelta.value = ''
  manualEditing.value = false
  try {
    const { data } = await api.post(
      `/projects/${projectId}/chapter-assignments/${task.id}/assist-generate`,
      { prompt: assistPrompt.value, mode: assistMode.value },
    )
    if (data.code === 0) {
      const content = data.data.content || ''
      editorContent.value = content
      chapters.value[task.chapter_no] = content
      message.success(
        data.data.stopped
          ? '已暂停，已生成部分已保存'
          : `章节 ${task.chapter_no} 生成完成，请人工审阅完善`,
      )
    } else {
      message.error(data.message || '辅助生成失败')
    }
  } catch (err) {
    message.error(getErrorMessage(err, '辅助生成失败'))
  } finally {
    assisting.value = false
    streamDelta.value = ''
  }
}

/** 暂停辅助生成：后端中止流式并将已累积部分按 mode 落库 */
const handleStopAssist = async () => {
  const task = editingTask.value
  if (!task) return
  stoppingAssist.value = true
  try {
    await api.post(
      `/projects/${projectId}/chapter-assignments/${task.id}/assist-generate/stop`,
    )
  } catch {
    message.error('暂停请求发送失败')
  } finally {
    stoppingAssist.value = false
  }
}

const handleSubmitFromEditor = async () => {
  const task = editingTask.value
  if (!task) return
  await handleSubmit(task)
}

/** 图片上传：POST /projects/{pid}/images → 在光标处插入 ![名称](代理路径)
 * 阶段 2：正文存代理路径（永不过期），渲染时由 MarkdownRenderer 换签名 URL */
const handleImageSelect = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  uploadingImage.value = true
  try {
    const form = new FormData()
    form.append('file', file)
    const { data } = await api.post(`/projects/${projectId}/images`, form)
    if (data.code === 0) {
      const name = file.name.replace(/\.[^.]+$/, '')
      insertAtCursor(
        `\n![${name}](/api/v1/projects/${projectId}/images/view?key=${encodeURIComponent(data.data.storage_key)})\n`,
      )
      message.success('图片已插入正文，保存后生效')
    } else {
      message.error(data.message || '图片上传失败')
    }
  } catch (err) {
    message.error(getErrorMessage(err, '图片上传失败'))
  } finally {
    uploadingImage.value = false
  }
}

/** 在编辑器光标处插入文本（无光标信息时追加到末尾） */
const insertAtCursor = (snippet: string) => {
  const root = (editorTextareaRef.value as { $el?: HTMLElement } | null)?.$el
  const el = root?.querySelector('textarea') ?? null
  const pos = el ? el.selectionStart : editorContent.value.length
  editorContent.value
    = editorContent.value.slice(0, pos) + snippet + editorContent.value.slice(pos)
}

/** 打开批注抽屉并拉取留言列表（项目成员可读） */
const openAnnotations = async () => {
  const task = editingTask.value
  if (!task) return
  annotOpen.value = true
  try {
    const { data } = await api.get(
      `/projects/${projectId}/chapter-assignments/${task.id}/annotations`,
    )
    if (data.code === 0) {
      annotations.value = data.data.items || []
    }
  } catch (err) {
    message.error(getErrorMessage(err, '批注加载失败'))
  }
}

const handleAddAnnotation = async () => {
  const task = editingTask.value
  const content = annotInput.value.trim()
  if (!task || !content) return
  annotSending.value = true
  try {
    const { data } = await api.post(
      `/projects/${projectId}/chapter-assignments/${task.id}/annotations`,
      { content },
    )
    if (data.code === 0) {
      annotInput.value = ''
      await openAnnotations()
    } else {
      message.error(data.message || '批注发送失败')
    }
  } catch (err) {
    message.error(getErrorMessage(err, '批注发送失败'))
  } finally {
    annotSending.value = false
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
  if (!task.id) return
  submittingId.value = task.id
  try {
    const { data } = await api.post(`/projects/${projectId}/chapter-assignments/${task.id}/submit`)
    if (data.code === 0) {
      message.success('已提交，等待负责人审核')
      closeEditor()
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

const openReview = (row: DivisionRow) => {
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
      // AI 辅助生成流式：仅渲染当前正在编制章节的 assist 事件
      if (
        data.source === 'assist'
        && editingTask.value
        && data.chapter_no === editingTask.value.chapter_no
      ) {
        if (data.type === 'section_token') {
          streamDelta.value += data.delta || ''
        } else if (data.type === 'section_done') {
          editorContent.value = data.content || ''
          chapters.value[data.chapter_no] = data.content || ''
        }
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
  color: var(--color-error);
}

.division__comment {
  font-size: 12px;
  color: var(--color-error);
}

.task-item {
  display: block;
  padding: 12px 16px;
  border-radius: 8px;
  background: var(--bg-subtle, rgba(0, 0, 0, 0.02));
}

.task-item + .task-item {
  margin-top: 12px;
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
  gap: 12px;
  margin-top: 12px;
}

/* 防误触：操作按钮增大热区间距，危险操作（提交审核）已有二次确认 */
.task-item__actions .ant-btn {
  min-width: 88px;
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

.editor-textarea {
  min-height: calc(100vh - 180px);
  font-size: 14px;
  line-height: 1.8;
}

.editor-preview {
  min-height: calc(100vh - 180px);
  padding: 12px 16px;
  border: 1px solid var(--border-color, #e5e5e5);
  border-radius: 6px;
}

.editor-preview__streaming {
  margin-top: 8px;
  font-size: 12px;
  color: var(--color-primary, #1677ff);
}

.assist-box {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.assist-box__actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.annot-time {
  margin-left: 8px;
  font-size: 12px;
  color: var(--text-secondary, #999);
}

.annot-input {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 16px;
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
