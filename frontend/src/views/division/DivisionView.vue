<template>
  <div class="division-view">
    <PageContainer
      title="方案生成与分工"
      subtitle="拖拽卡片切换状态，点击卡片编辑章节内容"
    >
      <!-- 章节分工（仅 owner 可见）：为章节指定负责人并推送分工 -->
      <a-card
        v-if="isOwner"
        title="章节分工"
        class="division-view__assign-card"
      >
        <template #extra>
          <a-button
            type="primary"
            size="small"
            :disabled="changedCount === 0"
            :loading="assigning"
            @click="handleAssign"
          >
            {{ changedCount > 0 ? `推送分工（${changedCount} 项）` : '推送分工' }}
          </a-button>
        </template>
        <EmptyState
          v-if="outline.length === 0"
          illustration="board"
          description="暂无大纲，请先到「方案大纲生成」页确认大纲"
        >
          <template #action>
            <a-button
              type="primary"
              @click="goToGenerate"
            >
              前往方案大纲生成
            </a-button>
          </template>
        </EmptyState>
        <a-table
          v-else
          :columns="assignColumns"
          :data-source="assignRows"
          :pagination="false"
          row-key="chapter_no"
          size="middle"
        >
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'chapter'">
              {{ record.chapter_no }} {{ record.title }}
            </template>
            <template v-else-if="column.key === 'assignee'">
              <a-select
                v-model:value="draftAssignees[record.chapter_no]"
                :options="memberOptions"
                placeholder="选择负责人"
                allow-clear
                show-search
                :filter-option="filterMember"
                style="width: 180px"
              />
            </template>
            <template v-else-if="column.key === 'status'">
              <a-tag
                v-if="record.status && TASK_STATUS_META[record.status as TaskStatus]"
                :color="TASK_STATUS_META[record.status as TaskStatus].color"
              >
                {{ TASK_STATUS_META[record.status as TaskStatus].text }}
              </a-tag>
              <span v-else>—</span>
            </template>
          </template>
        </a-table>
      </a-card>

      <!-- 工具栏 -->
      <div class="division-view__toolbar">
        <a-space wrap>
          <a-select
            v-if="isOwner"
            v-model:value="filterAssignee"
            placeholder="全部负责人"
            allow-clear
            style="width: 180px"
            :options="assigneeFilterOptions"
          />
          <a-tag v-else color="processing">
            仅显示我的任务
          </a-tag>
          <a-tag color="blue">
            共 {{ filteredItems.length }} 个章节
          </a-tag>
          <a-tag
            v-if="myTaskCount > 0"
            color="processing"
          >
            我的任务 {{ myTaskCount }}
          </a-tag>
        </a-space>
        <a-space>
          <a-button
            :loading="loading"
            @click="fetchAll"
          >
            <template #icon>
              <ReloadOutlined />
            </template>
            刷新
          </a-button>
          <a-tag
            v-if="approvedCount > 0"
            color="success"
          >
            已通过 {{ approvedCount }} 章
          </a-tag>
          <a-button
            v-if="approvedCount > 0"
            type="primary"
            :loading="confirmingDivision"
            @click="handleConfirmDivision"
          >
            <template #icon>
              <CheckCircleOutlined />
            </template>
            进入审阅
          </a-button>
          <a-button
            type="primary"
            ghost
            @click="goToGenerate"
          >
            <template #icon>
              <ArrowLeftOutlined />
            </template>
            返回大纲
          </a-button>
        </a-space>
      </div>

      <!-- 加载/错误状态 -->
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
            @click="fetchAll"
          >
            重试
          </a-button>
        </template>
      </ErrorState>

      <!-- 5列泳道看板（无任务时展示空态插画） -->
      <EmptyState
        v-else-if="items.length === 0"
        illustration="board"
        description="暂无分工任务，确认大纲并推送分工后任务将出现在看板"
      />

      <template v-else>
        <DivisionKanban
          :items="filteredItems"
          :is-owner="isOwner"
          @select="handleSelectTask"
          @move="handleMoveTask"
        />
      </template>
    </PageContainer>

    <!-- 章节编辑改为全屏富文本编辑器页面（路由跳转） -->
  </div>
</template>

<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  ArrowLeftOutlined,
  CheckCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons-vue'
import { fetchWorkflowStatus, confirmDivision } from '@/api/workflow'
import {
  fetchChapterAssignments,
  upsertChapterAssignments,
  acceptAssignment,
  submitAssignment,
  approveAssignment,
  rejectAssignment,
  fetchProject,
  fetchProjectMembers,
} from '@/api'
import PageContainer from '@/components/PageContainer.vue'
import ErrorState from '@/components/ErrorState.vue'
import EmptyState from '@/components/EmptyState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import DivisionKanban from './components/DivisionKanban.vue'
import { fetchCurrentUserRole } from '@/stores/currentUser'
import { TASK_STATUS_META } from '@/types'
import type { TaskStatus } from '@/types'
import { useDivisionBoard } from './composables/useDivisionBoard'

const route = useRoute()
const router = useRouter()
const projectId = route.params.projectId as string

const {
  loading,
  loadError,
  items,
  isOwner,
  outline,
  draftAssignees,
  assigning,
  filterAssignee,
  assignColumns,
  assignRows,
  memberOptions,
  filterMember,
  changedCount,
  assigneeFilterOptions,
  filteredItems,
  myTaskCount,
  approvedCount,
  confirmingDivision,
  handleConfirmDivision,
  fetchAll,
  handleAssign,
  handleSelectTask,
  handleMoveTask,
  goToGenerate,
} = useDivisionBoard(projectId, {
  api: {
    fetchChapterAssignments,
    upsertChapterAssignments,
    acceptAssignment,
    submitAssignment,
    approveAssignment,
    rejectAssignment,
    fetchProject,
    fetchProjectMembers,
    fetchWorkflowStatus,
    confirmDivision,
  },
  notify: {
    error: (m, d) => message.error(m, d),
    success: (m) => message.success(m),
    warning: (m) => message.warning(m),
    info: (m) => message.info(m),
  },
  routerPush: (to) => router.push(to),
  fetchCurrentUserRole,
})
</script>

<style scoped>
.division-view {
  width: 100%;
}

.division-view__assign-card {
  margin-bottom: 16px;
}

.division-view__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  padding: 12px 16px;
  background: var(--bg-surface);
  border: 1px solid var(--border-color);
  border-radius: var(--radius-lg);
}
</style>
