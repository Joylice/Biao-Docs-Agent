<template>
  <div class="workbench">
    <PageContainer
      title="工作台"
      subtitle="我的章节待办与项目进度一览"
    >
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
            @click="() => fetchSummary()"
          >
            重试
          </a-button>
        </template>
      </ErrorState>
      <template v-else>
        <!-- 快捷操作区 -->
        <div class="workbench__quick-actions">
          <a-button
            type="primary"
            @click="goProjects"
          >
            <template #icon>
              <PlusOutlined />
            </template>
            新建项目
          </a-button>
          <a-button @click="goProjects">
            <template #icon>
              <FolderOpenOutlined />
            </template>
            全部项目
          </a-button>
          <a-button @click="goMaterials">
            <template #icon>
              <DatabaseOutlined />
            </template>
            资料库
          </a-button>
        </div>

        <!-- 我的待办：5 桶（待领取/编制中/被打回/已提审/已通过），按项目分组 -->
        <div class="workbench__section-title">
          我的待办
        </div>
        <EmptyState
          v-if="totalTaskCount === 0"
          illustration="board"
          description="暂无待办任务，推送分工或领取任务后将出现在这里"
        />
        <div
          v-else
          class="workbench__buckets"
        >
          <a-card
            v-for="bucket in BUCKET_ORDER"
            :key="bucket"
            class="workbench__bucket"
          >
            <template #title>
              <span class="workbench__bucket-name">{{ BUCKET_META[bucket].text }}</span>
              <a-tag
                class="workbench__bucket-count"
                :color="BUCKET_META[bucket].color"
              >
                {{ summary.tasks[bucket].length }}
              </a-tag>
            </template>
            <div
              v-if="summary.tasks[bucket].length === 0"
              class="workbench__bucket-empty"
            >
              暂无任务
            </div>
            <div
              v-else
              class="workbench__task-list"
            >
              <!-- 按项目分组 -->
              <div
                v-for="group in groupedTasks[bucket]"
                :key="group.project_id"
                class="workbench__project-group"
              >
                <div
                  class="workbench__project-group-header"
                  @click="toggleProjectGroup(bucket, group.project_id)"
                >
                  <component
                    :is="expandedGroups.has(`${bucket}-${group.project_id}`) ? DownOutlined : RightOutlined"
                    class="workbench__project-group-arrow"
                  />
                  <a-tooltip :title="group.project_name">
                    <span class="workbench__project-group-name">
                      {{ projectAbbr(group.project_name) }}
                    </span>
                  </a-tooltip>
                  <a-tag
                    class="workbench__project-group-count"
                    :color="BUCKET_META[bucket].color"
                  >
                    {{ group.count }}
                  </a-tag>
                </div>
                <!-- 展开后显示章节列表 -->
                <div
                  v-show="expandedGroups.has(`${bucket}-${group.project_id}`)"
                  class="workbench__project-group-body"
                >
                  <div
                    v-for="item in group.tasks"
                    :key="item.assignment_id"
                    class="workbench__task"
                    @click="goDivision(item.project_id)"
                  >
                    <a-tooltip
                      :title="`${item.project_name} · ${item.chapter_no} ${item.title}`"
                    >
                      <span class="workbench__task-text">
                        {{ item.chapter_no }} {{ item.title }}
                      </span>
                    </a-tooltip>
                  </div>
                </div>
              </div>
            </div>
          </a-card>
        </div>

        <!-- 负责人视图：名下/参与项目进度看板 + 待审核清单（两者任一非空即显示） -->
        <template v-if="summary.my_projects.length > 0 || summary.owner_review_pending.length > 0">
          <div class="workbench__section-title">
            项目进度
          </div>
          <a-row :gutter="16">
            <a-col :span="summary.owner_review_pending.length > 0 ? 14 : 24">
              <a-card
                title="项目分工进度"
                class="workbench__board-card"
              >
                <div
                  v-for="proj in summary.my_projects"
                  :key="proj.project_id"
                  class="workbench__project"
                >
                  <div class="workbench__project-head">
                    <a
                      class="workbench__project-name"
                      :title="proj.project_name"
                      @click="goDivision(proj.project_id)"
                    >
                      {{ proj.project_name }}
                    </a>
                    <a-tag
                      v-if="proj.phase"
                      color="blue"
                    >
                      {{ PHASE_META[proj.phase] || proj.phase }}
                    </a-tag>
                    <span class="workbench__project-count">已通过 {{ proj.approved }}/{{ proj.total }}</span>
                  </div>
                  <a-progress
                    :percent="proj.percent"
                    size="small"
                  />
                  <a-space
                    :size="4"
                    wrap
                    class="workbench__project-dist"
                  >
                    <template
                      v-for="bucket in BUCKET_ORDER"
                      :key="bucket"
                    >
                      <a-tag
                        v-if="proj.status_dist[bucket]"
                        :color="BUCKET_META[bucket].color"
                      >
                        {{ BUCKET_META[bucket].text }} {{ proj.status_dist[bucket] }}
                      </a-tag>
                    </template>
                  </a-space>
                </div>
              </a-card>
            </a-col>
            <a-col
              v-if="summary.owner_review_pending.length > 0"
              :span="10"
            >
              <a-card
                class="workbench__board-card"
              >
                <template #title>
                  待我审核
                  <a-tag
                    color="warning"
                    class="workbench__bucket-count"
                  >
                    {{ summary.owner_review_pending.length }}
                  </a-tag>
                </template>
                <a-list
                  size="small"
                  :data-source="summary.owner_review_pending"
                >
                  <template #renderItem="{ item }">
                    <a-list-item
                      class="workbench__task"
                      @click="goDivision(item.project_id)"
                    >
                      <a-tooltip
                        :title="`${item.project_name} · ${item.chapter_no} ${item.title}`"
                      >
                        <span class="workbench__task-text">
                          {{ item.chapter_no }} {{ item.title }} ·
                          <span class="workbench__task-proj">{{ projectAbbr(item.project_name) }}</span>
                        </span>
                      </a-tooltip>
                    </a-list-item>
                  </template>
                </a-list>
              </a-card>
            </a-col>
          </a-row>
        </template>
      </template>
    </PageContainer>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  PlusOutlined,
  FolderOpenOutlined,
  DatabaseOutlined,
  DownOutlined,
  RightOutlined,
} from '@ant-design/icons-vue'
import { fetchWorkbenchSummary } from '@/api'
import PageContainer from '@/components/PageContainer.vue'
import EmptyState from '@/components/EmptyState.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSkeleton from '@/components/LoadingSkeleton.vue'
import {
  BUCKET_ORDER,
  BUCKET_META,
  PHASE_META,
  useWorkbench,
} from './composables/useWorkbench'
import type { BucketKey } from './composables/useWorkbench'

const router = useRouter()

const {
  loading,
  loadError,
  summary,
  totalTaskCount,
  groupedTasks,
  fetchSummary,
  goDivision,
  goProjects,
  goMaterials,
  projectAbbr,
} = useWorkbench({
  api: { fetchWorkbenchSummary },
  routerPush: (to) => router.push(to),
})

/** 展开的项目组集合（key = `${bucket}-${project_id}`） */
const expandedGroups = ref<Set<string>>(new Set())

/** 切换项目组展开/折叠 */
const toggleProjectGroup = (bucket: BucketKey, projectId: string) => {
  const key = `${bucket}-${projectId}`
  const next = new Set(expandedGroups.value)
  if (next.has(key)) {
    next.delete(key)
  } else {
    next.add(key)
  }
  expandedGroups.value = next
}
</script>

<style scoped>
.workbench {
  max-width: 1200px;
}

.workbench__quick-actions {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}

.workbench__section-title {
  margin: 4px 0 12px;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.workbench__buckets {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  margin-bottom: 20px;
}

.workbench__bucket {
  flex: 1 1 200px;
  min-width: 200px;
  background: var(--bg-surface);
}

.workbench__bucket-name {
  font-size: 13px;
  font-weight: 600;
}

.workbench__bucket-count {
  margin-left: var(--space-2);
}

.workbench__bucket-empty {
  padding: 12px 0;
  font-size: 12px;
  color: var(--text-secondary);
  text-align: center;
}

.workbench__task-list {
  max-height: 320px;
  overflow-y: auto;
}

/* 按项目分组 */
.workbench__project-group {
  margin-bottom: 4px;
}

.workbench__project-group-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  cursor: pointer;
  border-radius: 6px;
  transition: background 0.15s;
}

.workbench__project-group-header:hover {
  background: var(--bg-surface-hover);
}

.workbench__project-group-arrow {
  font-size: 10px;
  color: var(--text-tertiary);
  flex-shrink: 0;
  transition: transform 0.2s;
}

.workbench__project-group-name {
  flex: 1;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workbench__project-group-count {
  flex-shrink: 0;
  font-size: 11px;
  padding: 0 6px;
  line-height: 18px;
}

.workbench__project-group-body {
  padding-left: 16px;
  border-left: 2px solid var(--border-color);
  margin-left: 11px;
}

.workbench__task {
  cursor: pointer;
  transition: background 0.15s;
  padding: 6px 8px;
  border-radius: 4px;
}

.workbench__task:hover {
  background: var(--bg-surface-hover);
}

.workbench__task-text {
  font-size: 12px;
  color: var(--text-primary);
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workbench__task-proj {
  color: var(--text-tertiary);
  font-size: 11px;
}

.workbench__board-card {
  background: var(--bg-surface);
}

.workbench__project {
  padding: 12px 0;
  border-bottom: 1px solid var(--border-color-light);
}

.workbench__project:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.workbench__project:first-child {
  padding-top: 0;
}

.workbench__project-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.workbench__project-name {
  flex: 1;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-primary);
  cursor: pointer;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.workbench__project-name:hover {
  text-decoration: underline;
}

.workbench__project-count {
  font-size: 12px;
  color: var(--text-secondary);
  flex-shrink: 0;
}

.workbench__project-dist {
  margin-top: 8px;
}

/* 响应式 */
@media (max-width: 768px) {
  .workbench__bucket {
    flex: 1 1 100%;
    min-width: 100%;
  }
}
</style>
