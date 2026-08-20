<template>
  <div class="review-view">
    <PageContainer
      title="审阅与导出"
      subtitle="审阅生成内容，提交修改意见或确认导出"
    >
      <a-alert
        v-if="rewriting"
        type="info"
        show-icon
        class="mb-4"
        message="章节重写中，请稍候，完成后将自动刷新审阅内容"
      />

      <LoadingSkeleton
        v-if="loading"
        :rows="6"
      />
      <ErrorState
        v-else-if="loadError"
        :description="loadError"
      >
        <template #action>
          <a-button
            type="primary"
            @click="fetchStatus"
          >
            重试
          </a-button>
        </template>
      </ErrorState>
      <EmptyState
        v-else-if="chapterKeys.length === 0"
        description="暂无章节内容，请先在「方案大纲生成」页生成技术方案"
      />
      <template v-else>
        <!-- 左章节树 + 右内容 分栏 -->
        <a-layout
          class="review-layout"
          has-sider
        >
          <a-layout-sider
            v-model:collapsed="siderCollapsed"
            :width="232"
            :collapsed-width="0"
            breakpoint="lg"
            theme="light"
            class="review-sider"
          >
            <div class="review-sider__title">
              章节列表
              <a-tooltip :title="siderCollapsed ? '展开章节' : '收起章节'">
                <a-button
                  size="small"
                  type="text"
                  @click="siderCollapsed = !siderCollapsed"
                >
                  <template #icon>
                    <MenuFoldOutlined v-if="!siderCollapsed" />
                    <MenuUnfoldOutlined v-else />
                  </template>
                </a-button>
              </a-tooltip>
            </div>
            <a-tree
              v-if="!siderCollapsed"
              :tree-data="treeData"
              :selected-keys="[activeChapter]"
              :expanded-keys="expandedKeys"
              block-node
              class="chapter-tree"
              @select="onTreeSelect"
              @expand="onTreeExpand"
            >
              <template #title="{ dataRef }">
                <div
                  v-if="dataRef.kind === 'chapter'"
                  class="chapter-node__row"
                >
                  <span class="chapter-node__no">
                    {{ dataRef.chapter_no }} {{ dataRef.title }}
                  </span>
                  <a-tag
                    :color="chapterStateColor(dataRef.chapter_no)"
                    class="chapter-node__tag"
                  >
                    {{ chapterStateText(dataRef.chapter_no) }}
                  </a-tag>
                </div>
                <span
                  v-else
                  class="section-node__title"
                >{{ dataRef.title }}</span>
              </template>
            </a-tree>
          </a-layout-sider>

          <a-layout-content class="review-content">
            <!-- 顶部操作条 -->
            <div class="review-toolbar">
              <a-segmented
                v-model:value="mode"
                :options="modeOptions"
              />
              <a-button
                size="small"
                :loading="approving"
                :disabled="polling"
                @click="handleApprove"
              >
                通过
              </a-button>
              <a-button
                size="small"
                :disabled="polling"
                @click="openFeedbackDrawer"
              >
                反馈重写
              </a-button>
              <a-button
                v-if="mode === 'edit'"
                size="small"
                :loading="savingSection"
                :disabled="!hasEditDraft(activeChapter)"
                @click="handleSaveEditDraft"
              >
                保存
              </a-button>
              <a-button
                v-if="mode === 'edit'"
                size="small"
                @click="resetEditDraft"
              >
                重置
              </a-button>
            </div>

            <!-- 章节内容：编辑 / 预览（章级审阅，与生成粒度一致） -->
            <a-card
              class="chapter-card"
            >
              <template #title>
                <div class="chapter-card__title">
                  <span>章节 {{ activeChapter }}{{ activeChapterTitle ? ` ${activeChapterTitle}` : '' }}</span>
                  <a-tag
                    color="geekblue"
                    class="chapter-card__submitter"
                  >
                    提交人：{{ submitterOf(activeChapter) }}
                  </a-tag>
                </div>
              </template>
              <a-alert
                v-if="activeChapterRisks.length > 0"
                type="error"
                show-icon
                class="dq-risk-alert"
                :message="activeChapterRiskMessage"
              >
                <template #description>
                  <div
                    v-for="(risk, index) in activeChapterRisks"
                    :key="index"
                  >
                    {{ risk.clause_no }} {{ risk.title }} — {{ risk.recommendation }}
                  </div>
                </template>
              </a-alert>
              <a-textarea
                v-if="mode === 'edit'"
                v-model:value="editDrafts[activeChapter]"
                :rows="18"
                class="chapter-editor"
              />
              <MarkdownRenderer
                v-else
                :source="displayContent"
                :project-id="projectId"
              />
              <!-- 章节批注区：面板展开时懒加载该章批注列表 -->
              <a-collapse
                v-model:active-key="annotationPanelKeys"
                class="annotation-panel"
                @change="onAnnotationPanelChange"
              >
                <a-collapse-panel
                  :key="activeChapter"
                  :header="`批注（${annotationCountOf(activeChapter)}）`"
                >
                  <a-spin :spinning="annotationsLoading">
                    <a-empty
                      v-if="annotationListOf(activeChapter).length === 0"
                      description="暂无批注"
                    />
                    <div
                      v-else
                      class="annotation-list"
                    >
                      <div
                        v-for="item in annotationListOf(activeChapter)"
                        :key="item.id"
                        class="annotation-item"
                      >
                        <div class="annotation-item__header">
                          <span class="annotation-item__author">{{ item.created_by_name || '未知用户' }}</span>
                          <span class="annotation-item__time">{{ formatTime(item.created_at) }}</span>
                          <a-space
                            v-if="canManageAnnotation(item)"
                            size="small"
                            class="annotation-item__ops"
                          >
                            <a-button
                              size="small"
                              type="link"
                              @click="startEditAnnotation(item)"
                            >
                              编辑
                            </a-button>
                            <a-popconfirm
                              title="确认删除该条批注？"
                              ok-text="删除"
                              cancel-text="取消"
                              @confirm="handleDeleteAnnotation(activeChapter, item.id)"
                            >
                              <a-button
                                size="small"
                                type="link"
                                danger
                              >
                                删除
                              </a-button>
                            </a-popconfirm>
                          </a-space>
                        </div>
                        <a-textarea
                          v-if="editingAnnotationId === item.id"
                          v-model:value="editingAnnotationContent"
                          :rows="3"
                          :maxlength="2000"
                        />
                        <div
                          v-if="editingAnnotationId === item.id"
                          class="annotation-item__edit-ops"
                        >
                          <a-button
                            size="small"
                            @click="editingAnnotationId = ''"
                          >
                            取消
                          </a-button>
                          <a-button
                            size="small"
                            :loading="updatingAnnotation"
                            @click="handleUpdateAnnotation(activeChapter, item.id)"
                          >
                            保存
                          </a-button>
                        </div>
                        <a-typography-paragraph
                          v-else
                          :content="item.content"
                          class="annotation-item__content"
                        />
                      </div>
                    </div>
                    <div class="annotation-add">
                      <a-textarea
                        v-model:value="newAnnotation"
                        :rows="2"
                        :maxlength="2000"
                        placeholder="输入批注内容（1-2000 字），例如：此处需补充实施里程碑"
                      />
                      <a-button
                        size="small"
                        :loading="addingAnnotation"
                        :disabled="!newAnnotation.trim()"
                        @click="handleAddAnnotation(activeChapter)"
                      >
                        添加批注
                      </a-button>
                    </div>
                  </a-spin>
                </a-collapse-panel>
              </a-collapse>
            </a-card>
            <div class="feedback-hint">
              <InfoCircleOutlined /> 编辑保存后写入正式方案内容；或提交「反馈重写」触发 AI 重写
            </div>
          </a-layout-content>
        </a-layout>

        <!-- 底部操作区 -->
        <div class="actions">
          <a-button @click="goToGenerate">
            返回修改
          </a-button>
          <a-button
            type="primary"
            :loading="exporting"
            size="large"
            @click="handleExport"
          >
            导出 Word 文档
          </a-button>
          <a-button
            :loading="approving"
            :disabled="polling"
            size="large"
            @click="handleApprove"
          >
            审阅通过
          </a-button>
        </div>

        <!-- 导出结果 -->
        <a-result
          v-if="exportStatus === 'done'"
          status="success"
          title="导出成功"
          sub-title="技术方案已生成，可下载编辑"
        >
          <template #extra>
            <a-button
              @click="handleDownload"
            >
              下载文档
            </a-button>
          </template>
        </a-result>

        <!-- 版本库：评审通过快照（自动/手动），可下载与归档公司知识库 -->
        <a-card
          class="version-card"
          title="版本库"
        >
          <template #extra>
            <a-button
              v-if="isOwner"
              size="small"
              :loading="snapshotting"
              @click="openSnapshotModal"
            >
              手动快照
            </a-button>
          </template>
          <a-empty
            v-if="versions.length === 0"
            description="暂无版本：全部章节审核通过后将自动快照，owner 也可手动创建"
          />
          <a-list
            v-else
            :data-source="versions"
            size="small"
          >
            <template #renderItem="{ item }">
              <a-list-item>
                <div class="version-item">
                  <div class="version-item__main">
                    <a-tag color="blue">
                      v{{ item.version }}
                    </a-tag>
                    <a-tag
                      v-if="item.auto"
                      color="default"
                    >
                      自动快照
                    </a-tag>
                    <span class="version-item__note">
                      {{ item.snapshot_note || '—' }}
                    </span>
                    <span class="version-item__meta">
                      {{ item.created_by_name || '系统' }} · {{ formatTime(item.created_at) }}
                    </span>
                  </div>
                  <a-space>
                    <a-button
                      size="small"
                      @click="handleDownloadVersion(item, 'docx')"
                    >
                      下载 Word
                    </a-button>
                    <a-button
                      size="small"
                      @click="handleDownloadVersion(item, 'source')"
                    >
                      Markdown 源
                    </a-button>
                    <a-button
                      v-if="isOwner"
                      size="small"
                      @click="openArchiveModal(item)"
                    >
                      归档
                    </a-button>
                    <a-button
                      v-if="isOwner"
                      size="small"
                      danger
                      :loading="rollingBackId === item.id"
                      @click="confirmRollback(item)"
                    >
                      回滚
                    </a-button>
                  </a-space>
                </div>
              </a-list-item>
            </template>
          </a-list>
        </a-card>
      </template>
    </PageContainer>

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
            placeholder="例如：评审定稿版、客户要求调整后的版本"
          />
        </a-form-item>
      </a-form>
    </a-modal>

    <!-- 归档选库弹窗（限公司级知识库） -->
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
        <div class="feedback-redispatch-hint">
          归档后版本文档将入公司库分块向量化，供全公司方案生成检索
        </div>
      </a-form>
    </a-modal>

    <!-- 反馈重写面板 -->
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
            placeholder="描述需要修改的内容，例如：补充行业成功案例、调整表述为第一人称等"
          />
          <div class="feedback-redispatch-hint">
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
  </div>
</template>

<script setup lang="ts">
import { ref, computed, h, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message, Modal } from 'ant-design-vue'
import {
  ExclamationCircleOutlined,
  InfoCircleOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from '@ant-design/icons-vue'
import api from '@/api/client'
import { currentUserId, fetchCurrentUserRole } from '@/stores/currentUser'
import PageContainer from '@/components/PageContainer.vue'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import MarkdownRenderer from '@/components/MarkdownRenderer.vue'

interface WorkflowInterrupt {
  type: 'confirm_score_points' | 'confirm_outline' | 'review_request'
  message?: string
}

interface OutlineNode {
  chapter_no: string
  title: string
  sections?: string[]
}

interface WorkflowStatus {
  phase?: string
  progress?: number
  chapters?: Record<string, string>
  outline?: OutlineNode[]
  review_action?: string
  review_feedback?: Record<string, string>
  export_status?: string
  export_storage_key?: string
  error?: string
  interrupt?: WorkflowInterrupt | null
}

/** 左侧目录树节点：章（可选中审阅）+ 子节（纯展示，与生成粒度一致的章级导航） */
interface ChapterTreeNode {
  key: string
  kind: 'chapter' | 'section'
  chapter_no: string
  title: string
  selectable: boolean
  children?: ChapterTreeNode[]
}

/** 版本库条目（GET /projects/{pid}/versions） */
interface VersionItem {
  id: string
  version: number
  snapshot_note: string | null
  created_by: string | null
  created_by_name: string | null
  auto: boolean
  created_at: string | null
}

/** 章节批注条目（GET /projects/{pid}/chapters/{chapter_no}/annotations） */
interface AnnotationItem {
  id: string
  chapter_no: string
  content: string
  created_by: string
  created_by_name: string
  created_at: string
  updated_at: string | null
}

/** 公司级知识库选项（归档选库弹窗） */
interface KbBaseOption {
  value: string
  label: string
}

const route = useRoute()
const router = useRouter()
const projectId = route.params.projectId as string

const loading = ref(false)
const loadError = ref('')
const chapters = ref<Record<string, string>>({})
const outline = ref<OutlineNode[]>([])
/** 提交人标注：chapter_no → 分工提交人姓名（无分工显示 AI 生成/未分配） */
const submitters = ref<Record<string, string>>({})
const expandedKeys = ref<string[]>([])
const activeChapter = ref('')

/* ---------------- 废标风险（阶段 H：章节卡片命中提示，静默降级） ---------------- */
/** 废标风险命中条目（GET /projects/{pid}/disqualification-risks 按章节号聚合） */
interface DisqualificationRiskItem {
  clause_no: string
  title: string
  severity: string
  risk_category: string
  recommendation: string
  matched?: boolean
}

/** 章节号 → 命中条款列表（失败降级为空对象） */
const disqualificationRisks = ref<Record<string, DisqualificationRiskItem[]>>({})

const activeChapterRisks = computed<DisqualificationRiskItem[]>(
  () => disqualificationRisks.value[activeChapter.value] || [],
)

const activeChapterRiskMessage = computed(() => {
  const hits = activeChapterRisks.value
  if (hits.length === 0) return ''
  return hits.length > 1
    ? `废标风险：${hits[0].title} 等 ${hits.length} 条`
    : `废标风险：${hits[0].title}`
})

/** 拉取废标风险章节聚合（失败降级为空对象，不阻塞审阅） */
const fetchDisqualificationRisks = async () => {
  try {
    const res = await api.get(`/projects/${projectId}/disqualification-risks`)
    disqualificationRisks.value = res.data?.data?.risks || {}
  } catch {
    disqualificationRisks.value = {}
  }
}
const reviewFeedback = ref<Record<string, string>>({})
const approving = ref(false)
const submittingFeedback = ref(false)
const exporting = ref(false)
const exportStatus = ref('')
const exportStorageKey = ref('')
const rewriting = ref(false)

// 展示层状态：侧栏折叠 / 编辑-预览模式 / 本地编辑草稿 / 反馈面板
const siderCollapsed = ref(false)
const mode = ref<'edit' | 'preview'>('preview')
const modeOptions = [
  { label: '预览', value: 'preview' },
  { label: '编辑', value: 'edit' },
]
const editDrafts = ref<Record<string, string>>({})
const feedbackDrawerOpen = ref(false)
const feedbackComment = ref('')

// 版本库：列表/手动快照/下载/归档公司库/回滚
const isOwner = ref(false)
const versions = ref<VersionItem[]>([])
const snapshotModalOpen = ref(false)
const snapshotNote = ref('')
const snapshotting = ref(false)
const archiveModalOpen = ref(false)
const archiving = ref(false)
const archiveKbId = ref<string | undefined>(undefined)
const archiveTarget = ref<VersionItem | null>(null)
const companyBases = ref<KbBaseOption[]>([])
const rollingBackId = ref('')

// 章节批注：按章缓存列表（面板展开时懒加载），各章独立维护
const annotationMap = ref<Record<string, AnnotationItem[]>>({})
const annotationLoaded = ref<Record<string, boolean>>({})
const annotationPanelKeys = ref<string[]>([])
const annotationsLoading = ref(false)
const newAnnotation = ref('')
const addingAnnotation = ref(false)
const editingAnnotationId = ref('')
const editingAnnotationContent = ref('')
const updatingAnnotation = ref(false)

const chapterKeys = computed(() => Object.keys(chapters.value))
const polling = computed(() => pollTimer !== null)

/** 全量 2 级目录树：outline 章 + 子节；仅有内容不在 outline 的章兼容补充 */
const treeData = computed<ChapterTreeNode[]>(() => {
  const nodes: ChapterTreeNode[] = outline.value.map((c) => ({
    key: c.chapter_no,
    kind: 'chapter',
    chapter_no: c.chapter_no,
    title: c.title,
    selectable: true,
    children: (c.sections || []).map((s, idx) => ({
      key: `${c.chapter_no}-s${idx}`,
      kind: 'section',
      chapter_no: c.chapter_no,
      title: s,
      selectable: false,
    })),
  }))
  const outlineNos = new Set(outline.value.map((c) => c.chapter_no))
  for (const no of chapterKeys.value) {
    if (!outlineNos.has(no)) {
      nodes.push({ key: no, kind: 'chapter', chapter_no: no, title: '', selectable: true })
    }
  }
  return nodes
})

const activeChapterTitle = computed(
  () => outline.value.find((c) => c.chapter_no === activeChapter.value)?.title || '',
)

/** 提交人：有分工显示提交人姓名，无分工显示「AI 生成/未分配」 */
const submitterOf = (chapterNo: string): string =>
  submitters.value[chapterNo] || 'AI 生成/未分配'

const onTreeSelect = (keys: string[]) => {
  if (keys.length > 0) selectChapter(keys[0])
}

const onTreeExpand = (keys: string[]) => {
  expandedKeys.value = keys
}

/** 展示内容：本地编辑草稿优先，无草稿时用服务端章节原文 */
const displayContent = computed(
  () => editDrafts.value[activeChapter.value] ?? chapters.value[activeChapter.value] ?? '',
)

/** 本地草稿是否与已保存内容不同（未保存标记：提醒保存） */
const hasEditDraft = (chapterNo: string): boolean => {
  const draft = editDrafts.value[chapterNo]
  return draft !== undefined && draft !== chapters.value[chapterNo]
}

/** 章节状态（展示层语义）：待重写（曾提交反馈）> 已修改（未保存草稿）> 待审 */
const chapterStateText = (chapterNo: string): string => {
  if (reviewFeedback.value[chapterNo]) return '待重写'
  if (hasEditDraft(chapterNo)) return '已修改'
  return '待审'
}

const chapterStateColor = (chapterNo: string): string => {
  if (reviewFeedback.value[chapterNo]) return 'orange'
  if (hasEditDraft(chapterNo)) return 'blue'
  return 'default'
}

const selectChapter = (chapterNo: string) => {
  activeChapter.value = chapterNo
  if (editDrafts.value[chapterNo] === undefined) {
    editDrafts.value[chapterNo] = chapters.value[chapterNo] || ''
  }
}

const resetEditDraft = () => {
  editDrafts.value[activeChapter.value] = chapters.value[activeChapter.value] || ''
}

const savingSection = ref(false)

/** 保存章节编辑：PUT sections/{chapter_no} 直接落库，成功后清除本地草稿 */
const handleSaveEditDraft = async () => {
  const no = activeChapter.value
  const content = editDrafts.value[no]?.trim() ?? ''
  if (!no) return
  if (!content) {
    message.warning('章节内容不能为空')
    return
  }
  if (savingSection.value) return
  savingSection.value = true
  try {
    await api.put(`/projects/${projectId}/workflow/sections/${no}`, { content })
    chapters.value[no] = content
    delete editDrafts.value[no]
    message.success(`章节 ${no} 已保存到正式方案`)
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '章节保存失败')
  } finally {
    savingSection.value = false
  }
}

// ---------- 章节批注 ----------

const annotationListOf = (chapterNo: string): AnnotationItem[] =>
  annotationMap.value[chapterNo] || []

const annotationCountOf = (chapterNo: string): number =>
  annotationListOf(chapterNo).length

/** 批注编辑/删除权限：作者本人或项目 owner（后端兜底，此处仅控制按钮可见性） */
const canManageAnnotation = (item: AnnotationItem): boolean =>
  item.created_by === currentUserId.value || isOwner.value

/** 批注面板展开：首次展开时懒加载该章批注（时间正序由后端保证） */
const onAnnotationPanelChange = (keys: string | string[]) => {
  const active = Array.isArray(keys) ? keys : [keys]
  for (const no of active) {
    if (no && !annotationLoaded.value[no]) loadAnnotations(no)
  }
}

const loadAnnotations = async (chapterNo: string) => {
  annotationsLoading.value = true
  try {
    const res = await api.get(`/projects/${projectId}/chapters/${chapterNo}/annotations`)
    if (res.data?.code === 0) {
      annotationMap.value[chapterNo] = res.data.data.items || []
      annotationLoaded.value[chapterNo] = true
    } else {
      message.error(res.data?.message || '批注加载失败')
    }
  } catch {
    message.error('批注加载失败')
  } finally {
    annotationsLoading.value = false
  }
}

/** 添加批注（仅章节负责人/项目负责人可写，后端强制；403 提示无权限） */
const handleAddAnnotation = async (chapterNo: string) => {
  const content = newAnnotation.value.trim()
  if (!chapterNo || !content) return
  addingAnnotation.value = true
  try {
    const res = await api.post(`/projects/${projectId}/chapters/${chapterNo}/annotations`, { content })
    if (res.data?.code === 0) {
      newAnnotation.value = ''
      await loadAnnotations(chapterNo)
    } else {
      message.error(res.data?.message || '批注添加失败')
    }
  } catch (err) {
    const status = (err as { response?: { status?: number } })?.response?.status
    if (status === 403) {
      message.error('无该章节批注权限（仅章节负责人/项目负责人可写）')
    } else {
      const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
      message.error(msg || '批注添加失败')
    }
  } finally {
    addingAnnotation.value = false
  }
}

const startEditAnnotation = (item: AnnotationItem) => {
  editingAnnotationId.value = item.id
  editingAnnotationContent.value = item.content
}

/** 更新批注（仅作者本人或项目负责人，后端强制） */
const handleUpdateAnnotation = async (chapterNo: string, annotationId: string) => {
  const content = editingAnnotationContent.value.trim()
  if (!content) {
    message.warning('批注内容不能为空')
    return
  }
  updatingAnnotation.value = true
  try {
    const res = await api.put(
      `/projects/${projectId}/chapters/${chapterNo}/annotations/${annotationId}`,
      { content },
    )
    if (res.data?.code === 0) {
      editingAnnotationId.value = ''
      const items = annotationMap.value[chapterNo] || []
      const idx = items.findIndex((it) => it.id === annotationId)
      if (idx >= 0) items[idx] = { ...items[idx], ...res.data.data }
      message.success('批注已更新')
    } else {
      message.error(res.data?.message || '批注更新失败')
    }
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '批注更新失败')
  } finally {
    updatingAnnotation.value = false
  }
}

/** 删除批注（仅作者本人或项目负责人，后端强制） */
const handleDeleteAnnotation = async (chapterNo: string, annotationId: string) => {
  try {
    const res = await api.delete(
      `/projects/${projectId}/chapters/${chapterNo}/annotations/${annotationId}`,
    )
    if (res.data?.code === 0) {
      annotationMap.value[chapterNo] = (annotationMap.value[chapterNo] || []).filter(
        (it) => it.id !== annotationId,
      )
      message.success('批注已删除')
    } else {
      message.error(res.data?.message || '批注删除失败')
    }
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '批注删除失败')
  }
}

let pollTimer: number | null = null

const stopPolling = () => {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const applyStatus = (data: WorkflowStatus) => {
  chapters.value = data.chapters || {}
  outline.value = data.outline || []
  reviewFeedback.value = data.review_feedback || {}
  exportStatus.value = data.export_status || ''
  exportStorageKey.value = data.export_storage_key || ''
  if (!activeChapter.value) {
    const keys = Object.keys(chapters.value)
    if (keys.length > 0) activeChapter.value = keys[0]
  }
  // 初始化编辑草稿（保留已输入内容）
  for (const chapterNo of Object.keys(chapters.value)) {
    if (editDrafts.value[chapterNo] === undefined) {
      editDrafts.value[chapterNo] = chapters.value[chapterNo] || ''
    }
  }
  // 目录树默认展开全部章节点
  if (expandedKeys.value.length === 0) {
    expandedKeys.value = outline.value.map((c) => c.chapter_no)
  }
}

const fetchStatus = async (): Promise<WorkflowStatus | undefined> => {
  const res = await api.get(`/projects/${projectId}/workflow/status`)
  return res.data?.data as WorkflowStatus | undefined
}

/** 拉取分工列表供提交人标注（可选增强，失败不阻塞审阅） */
const fetchSubmitters = async () => {
  try {
    const res = await api.get(`/projects/${projectId}/chapter-assignments`)
    const items = (res.data?.data?.items || []) as {
      chapter_no: string
      submitted_by_name?: string
    }[]
    const map: Record<string, string> = {}
    for (const it of items) {
      if (it.submitted_by_name) map[it.chapter_no] = it.submitted_by_name
    }
    submitters.value = map
  } catch {
    // 提交人标注失败时降级显示「AI 生成/未分配」
  }
}

/** 版本库列表刷新（快照/归档/回滚成功后复用） */
const fetchVersions = async () => {
  try {
    const res = await api.get(`/projects/${projectId}/versions`)
    if (res.data?.code === 0) versions.value = res.data.data.items || []
  } catch {
    // 版本库加载失败不阻塞审阅主流程
  }
}

/** 项目 owner 判定（手动快照/归档/回滚入口可见性） */
const fetchOwnerFlag = async () => {
  try {
    await fetchCurrentUserRole()
    const res = await api.get(`/projects/${projectId}`)
    if (res.data?.code === 0) {
      isOwner.value = res.data.data.owner_id === currentUserId.value
    }
  } catch {
    isOwner.value = false
  }
}

const formatTime = (iso: string | null): string => {
  if (!iso) return '—'
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('zh-CN', { hour12: false })
}

const openSnapshotModal = () => {
  snapshotNote.value = ''
  snapshotModalOpen.value = true
}

/** 手动快照（仅 owner）：POST versions 续号入库 */
const handleCreateSnapshot = async () => {
  snapshotting.value = true
  try {
    const res = await api.post(`/projects/${projectId}/versions`, {
      snapshot_note: snapshotNote.value.trim() || null,
    })
    if (res.data?.code === 0) {
      message.success(`版本 v${res.data.data.version} 快照已创建`)
      snapshotModalOpen.value = false
      await fetchVersions()
    } else {
      message.error(res.data?.message || '快照创建失败')
    }
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '快照创建失败')
  } finally {
    snapshotting.value = false
  }
}

/** 版本下载：取签名 URL 后新窗打开（docx / Markdown 源二选一） */
const handleDownloadVersion = async (item: VersionItem, type: 'docx' | 'source') => {
  try {
    const res = await api.get(`/projects/${projectId}/versions/${item.id}/download`, {
      params: { type },
    })
    if (res.data?.code === 0 && res.data.data.url) {
      window.open(res.data.data.url, '_blank')
    } else {
      message.error(res.data?.message || '下载链接生成失败')
    }
  } catch {
    message.error('下载链接生成失败')
  }
}

/** 归档选库弹窗：拉取公司级知识库列表 */
const openArchiveModal = async (item: VersionItem) => {
  archiveTarget.value = item
  archiveKbId.value = undefined
  archiveModalOpen.value = true
  if (companyBases.value.length > 0) return
  try {
    const res = await api.get('/kb-bases')
    if (res.data?.code === 0) {
      companyBases.value = (res.data.data.items || [])
        .filter((b: { scope: string }) => b.scope === 'company')
        .map((b: { id: string; name: string }) => ({ value: b.id, label: b.name }))
    }
  } catch {
    message.error('知识库列表加载失败')
  }
}

/** 归档：版本文档入公司库（全局素材 + 分块向量化入队） */
const handleArchive = async () => {
  if (!archiveTarget.value || !archiveKbId.value) return
  archiving.value = true
  try {
    const res = await api.post(
      `/projects/${projectId}/versions/${archiveTarget.value.id}/archive`,
      { kb_id: archiveKbId.value },
    )
    if (res.data?.code === 0) {
      message.success(`已归档：${res.data.data.title}`)
      archiveModalOpen.value = false
    } else {
      message.error(res.data?.message || '归档失败')
    }
  } catch (err) {
    const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
    message.error(msg || '归档失败')
  } finally {
    archiving.value = false
  }
}

/** 版本回滚二次确认（仅 owner）：快照覆盖当前全部章节内容，章节状态回退草稿 */
const confirmRollback = (item: VersionItem) => {
  Modal.confirm({
    title: '回滚版本',
    content: `将用版本 v${item.version} 的快照覆盖当前全部章节内容，且章节状态回退为草稿。确认回滚？`,
    okText: '确认回滚',
    cancelText: '取消',
    okButtonProps: { danger: true },
    icon: () => h(ExclamationCircleOutlined),
    onOk: () => handleRollback(item),
  })
}

/** 执行回滚：成功后刷新版本列表与章节正文数据（复用 fetchStatus/applyStatus） */
const handleRollback = async (item: VersionItem) => {
  rollingBackId.value = item.id
  try {
    const res = await api.post(`/projects/${projectId}/versions/${item.id}/rollback`)
    if (res.data?.code !== 0) {
      message.error(res.data?.message || '版本回滚失败')
      return
    }
    const restored = res.data.data?.chapters_restored ?? 0
    await fetchVersions()
    // 回滚后章节正文与状态已变化：重拉状态并清空本地编辑草稿
    const data = await fetchStatus()
    if (data) {
      applyStatus(data)
      editDrafts.value = {}
    }
    message.success(`回滚成功，已恢复 ${restored} 个章节内容`)
  } catch (err) {
    const status = (err as { response?: { status?: number } })?.response?.status
    if (status === 403) {
      message.error('仅项目负责人可回滚')
    } else {
      const msg = (err as { response?: { data?: { message?: string } } })?.response?.data?.message
      message.error(msg || '版本回滚失败')
    }
  } finally {
    rollingBackId.value = ''
  }
}

/** 轮询状态直到满足终止条件（最长约 3 分钟）. */
const pollUntil = (until: (data: WorkflowStatus) => boolean, onDone?: (data: WorkflowStatus) => void) => {
  stopPolling()
  let attempts = 0
  pollTimer = window.setInterval(async () => {
    attempts += 1
    try {
      const data = await fetchStatus()
      if (!data) return
      applyStatus(data)
      if (data.error) {
        stopPolling()
        rewriting.value = false
        message.error(data.error)
        return
      }
      if (until(data)) {
        stopPolling()
        onDone?.(data)
      } else if (attempts >= 90) {
        stopPolling()
        rewriting.value = false
        message.warning('等待超时，请稍后手动刷新状态')
      }
    } catch {
      // 轮询中的瞬时错误不打断，继续重试
    }
  }, 2000)
}

const handleApprove = async () => {
  approving.value = true
  try {
    const res = await api.post(`/projects/${projectId}/workflow/confirm-review`, {
      action: 'approved',
    })
    if (res.data?.code !== 0) {
      message.error(res.data?.message || '审阅确认失败')
      return
    }
    message.success('审阅通过，正在生成导出文档...')
    pollUntil(
      (data) => data.export_status === 'done',
      () => message.success('导出完成，可下载文档'),
    )
  } catch {
    message.error('审阅确认失败')
  } finally {
    approving.value = false
  }
}

const openFeedbackDrawer = () => {
  feedbackComment.value = ''
  feedbackDrawerOpen.value = true
}

/** 反馈重写：仅提交当前章节的意见（API 结构与原先一致） */
const handleSubmitChapterFeedback = async () => {
  const comment = feedbackComment.value.trim()
  if (!comment) {
    message.warning('请填写修改意见')
    return
  }
  if (!activeChapter.value) {
    message.warning('请先选择章节')
    return
  }
  submittingFeedback.value = true
  try {
    const res = await api.post(`/projects/${projectId}/workflow/confirm-review`, {
      action: 'feedback',
      feedback: { [activeChapter.value]: comment },
    })
    if (res.data?.code !== 0) {
      message.error(res.data?.message || '提交修改意见失败')
      return
    }
    // 意见全部回派负责人 → 无 AI 重写，等待重编后复审
    if (res.data?.data?.next_phase === 'redispatch') {
      message.success('修改意见已回派给章节负责人，重编提交后复审')
      feedbackDrawerOpen.value = false
      return
    }
    message.success('修改意见已提交，已触发章节重写')
    feedbackDrawerOpen.value = false
    rewriting.value = true
    // 两段式终止条件：先等 interrupt 消失（后台已消费 resume、重写进行中），
    // 再等 review_request 重现（重写完成），避免被提交瞬间尚未消费的旧 interrupt 误判
    let sawCleared = false
    pollUntil(
      (data) => {
        if (!data.interrupt) sawCleared = true
        return sawCleared && data.interrupt?.type === 'review_request'
      },
      () => {
        rewriting.value = false
        // 重写完成后清除该章意见草稿，保留用户其它草稿
        if (editDrafts.value[activeChapter.value] !== undefined) {
          editDrafts.value[activeChapter.value] = chapters.value[activeChapter.value] || ''
        }
        message.success('章节重写完成，请重新审阅')
      },
    )
  } catch {
    message.error('提交修改意见失败')
  } finally {
    submittingFeedback.value = false
  }
}

const handleExport = async () => {
  exporting.value = true
  try {
    const res = await api.get(`/projects/${projectId}/workflow/export`)
    const data = res.data?.data
    exportStatus.value = data?.export_status || 'pending'
    exportStorageKey.value = data?.export_storage_key || ''
    if (exportStatus.value === 'done') {
      message.success('导出成功')
    }
  } catch {
    message.error('导出失败')
  } finally {
    exporting.value = false
  }
}

const handleDownload = async () => {
  if (!exportStorageKey.value) {
    message.info('文档尚未就绪，请先完成导出')
    return
  }
  message.success(`文档已就绪（存储标识：${exportStorageKey.value}）`)
}

const goToGenerate = () => {
  router.push({ name: 'Generate', params: { projectId } })
}

onMounted(async () => {
  loading.value = true
  loadError.value = ''
  try {
    const data = await fetchStatus()
    if (data) applyStatus(data)
    await fetchSubmitters()
    await fetchOwnerFlag()
    await fetchVersions()
    await fetchDisqualificationRisks()
  } catch {
    loadError.value = '审阅状态加载失败'
  } finally {
    loading.value = false
  }
})

onUnmounted(() => {
  stopPolling()
})
</script>

<style scoped>
.review-view { max-width: 1200px; }
.mb-4 { margin-bottom: 16px; }

.review-layout {
  background: transparent;
}

.review-sider {
  background: var(--card-bg);
  border-radius: 8px;
  overflow: hidden;
  margin-right: 16px;
}

.review-sider__title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  font-weight: 600;
  border-bottom: 1px solid var(--border-color, #e8e8e8);
}

.chapter-tree {
  max-height: 560px;
  overflow-y: auto;
}

.chapter-node {
  cursor: pointer;
  padding: 10px 16px !important;
  border-bottom: 1px solid var(--border-color, #f0f0f0);
}

.chapter-node:hover {
  background: var(--bg-hover, #f5f7fa);
}

.chapter-node--active {
  background: var(--bg-block, rgba(21, 101, 192, 0.06));
  border-left: 3px solid var(--color-primary);
}

.chapter-node__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
}

.chapter-node__no {
  font-size: 13px;
  font-weight: 500;
}

.chapter-node__tag {
  flex-shrink: 0;
  font-size: 12px;
  line-height: 18px;
}

.section-node__title {
  font-size: 12px;
  color: var(--text-secondary, #8c8c8c);
}

.chapter-card__title {
  display: flex;
  align-items: center;
  gap: 12px;
}

.chapter-card__submitter {
  font-weight: 400;
}

.feedback-redispatch-hint {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-secondary, #999);
}

.review-content {
  background: transparent;
  min-width: 0;
}

.review-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.chapter-card {
  background: var(--card-bg);
  min-height: 360px;
}

.chapter-editor {
  font-family: 'Consolas', 'Microsoft YaHei', monospace;
  font-size: 13px;
  line-height: 1.7;
}

.feedback-hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--text-secondary, #999);
}

/* 章节批注区 */
.annotation-panel {
  margin-top: 16px;
  background: transparent;
}

.annotation-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.annotation-item {
  padding: 8px 12px;
  border: 1px solid var(--border-color, #f0f0f0);
  border-radius: 6px;
  background: var(--bg-block, rgba(0, 0, 0, 0.02));
}

.annotation-item__header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.annotation-item__author {
  font-size: 13px;
  font-weight: 600;
}

.annotation-item__time {
  font-size: 12px;
  color: var(--text-secondary, #999);
}

.annotation-item__ops {
  margin-left: auto;
}

.annotation-item__content {
  margin-bottom: 0;
  white-space: pre-wrap;
}

.annotation-item__edit-ops {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 6px;
}

.annotation-add {
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-start;
}

.actions { display: flex; gap: 12px; justify-content: flex-end; margin-top: 24px; }

.version-card {
  margin-top: 24px;
  background: var(--card-bg);
}

.version-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
}

.version-item__main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  flex-wrap: wrap;
}

.version-item__note {
  font-size: 13px;
}

.version-item__meta {
  font-size: 12px;
  color: var(--text-secondary, #999);
}

.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 8px;
}

.dq-risk-alert {
  margin-bottom: 12px;
}
</style>
