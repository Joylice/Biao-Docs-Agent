<template>
  <div class="chapter-nav">
    <div class="chapter-nav__header">
      <span class="chapter-nav__title">章节目录</span>
      <a-button
        size="small"
        type="text"
        @click="loadData"
      >
        <template #icon>
          <ReloadOutlined />
        </template>
      </a-button>
    </div>

    <div class="chapter-nav__search">
      <a-input
        v-model:value="searchText"
        placeholder="搜索章节..."
        allow-clear
        size="small"
      >
        <template #prefix>
          <SearchOutlined />
        </template>
      </a-input>
    </div>

    <a-spin :spinning="loading">
      <div
        v-if="filteredTree.length === 0 && !loading"
        class="chapter-nav__empty"
      >
        <EmptyState
          illustration="folder"
          description="暂无分工章节"
        />
      </div>
      <div
        v-else
        class="chapter-nav__tree"
      >
        <div
          v-for="chapter in filteredTree"
          :key="chapter.chapter_no"
          class="chapter-nav__chapter"
        >
          <div
            class="chapter-nav__chapter-head"
            :class="{ 'chapter-nav__chapter-head--active': isActive(chapter.chapter_no) }"
            @click="handleNavigate(chapter)"
          >
            <span
              class="chapter-nav__expand"
              @click.stop="toggleExpand(chapter.chapter_no)"
            >
              <CaretRightOutlined
                v-if="chapter.children?.length && !expandedSet.has(chapter.chapter_no)"
              />
              <CaretDownOutlined
                v-else-if="chapter.children?.length"
              />
            </span>
            <span class="chapter-nav__chapter-no">{{ chapter.chapter_no }}</span>
            <span
              class="chapter-nav__chapter-title"
              :title="chapter.title"
            >{{ chapter.title }}</span>
            <a-tag
              v-if="chapter.status"
              :color="statusColor(chapter.status)"
              class="chapter-nav__status-tag"
            >
              {{ statusText(chapter.status) }}
            </a-tag>
          </div>

          <div
            v-if="chapter.children?.length && expandedSet.has(chapter.chapter_no)"
            class="chapter-nav__sections"
          >
            <div
              v-for="section in chapter.children"
              :key="section.chapter_no"
              class="chapter-nav__section"
              :class="{ 'chapter-nav__section--active': isActive(section.chapter_no) }"
              @click="handleNavigate(section)"
            >
              <span class="chapter-nav__section-no">{{ section.chapter_no }}</span>
              <span
                class="chapter-nav__section-title"
                :title="section.title"
              >{{ section.title }}</span>
              <a-tag
                v-if="section.status"
                :color="statusColor(section.status)"
                class="chapter-nav__status-tag chapter-nav__status-tag--small"
              >
                {{ statusText(section.status) }}
              </a-tag>
            </div>
          </div>
        </div>
      </div>
    </a-spin>

    <div class="chapter-nav__footer">
      <span class="chapter-nav__count">共 {{ totalCount }} 个章节</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  ReloadOutlined,
  SearchOutlined,
  CaretRightOutlined,
  CaretDownOutlined,
} from '@ant-design/icons-vue'
import { fetchChapterAssignments } from '@/api'
import EmptyState from '@/components/EmptyState.vue'
import type { AssignmentNode } from '@/types'

interface NavChapter {
  id?: string
  chapter_no: string
  title: string
  status?: string | null
  assignee_id?: string | null
  children?: NavChapter[]
}

const props = defineProps<{
  projectId: string
  currentChapterNo: string
}>()

const emit = defineEmits<{
  (e: 'navigate', chapterNo: string): void
}>()

const router = useRouter()
const loading = ref(false)
const tree = ref<NavChapter[]>([])
const searchText = ref('')
const expandedSet = ref<Set<string>>(new Set())

/** 状态文本映射 */
const statusText = (status: string): string => {
  const map: Record<string, string> = {
    pending: '待领取',
    in_progress: '编制中',
    rejected: '被打回',
    submitted: '已提审',
    approved: '已通过',
  }
  return map[status] || status
}

/** 状态颜色映射 */
const statusColor = (status: string): string => {
  const map: Record<string, string> = {
    pending: 'default',
    in_progress: 'processing',
    rejected: 'error',
    submitted: 'warning',
    approved: 'success',
  }
  return map[status] || 'default'
}

/**
 * 将分工树转换为导航树（1 级章 + 2 级子节完整展示）。
 * 章级行始终保留：章级分工（有 id）或聚合行（展开为子节，id 为 null）都展示；
 * 仅当章级无 id 且无子节时过滤（大纲中未推送分工的章）。
 */
const transformTree = (nodes: AssignmentNode[]): NavChapter[] => {
  return nodes
    .filter((node) => node.id || (node.children?.length ?? 0) > 0)
    .map((node) => ({
      id: node.id ?? undefined,
      chapter_no: node.chapter_no,
      title: node.title,
      status: node.status,
      assignee_id: node.assignee_id,
      children: node.children?.length ? transformTree(node.children) : undefined,
    }))
}

/** 加载分工数据 */
const loadData = async () => {
  if (!props.projectId) return
  loading.value = true
  try {
    const { data } = await fetchChapterAssignments(props.projectId)
    const items = data.data?.items ?? []
    tree.value = transformTree(items)
    // 默认展开所有有子节的章节
    tree.value.forEach((chapter) => {
      if (chapter.children?.length) {
        expandedSet.value.add(chapter.chapter_no)
      }
    })
    // 如果当前章节在某个子节中，确保父章节展开
    const currentNo = props.currentChapterNo
    if (currentNo.includes('.')) {
      const parentNo = currentNo.split('.')[0]
      expandedSet.value.add(parentNo)
    }
  } catch {
    message.error('章节目录加载失败')
  } finally {
    loading.value = false
  }
}

/** 搜索过滤 */
const filteredTree = computed<NavChapter[]>(() => {
  if (!searchText.value.trim()) return tree.value
  const keyword = searchText.value.toLowerCase()
  const filtered: NavChapter[] = []
  for (const chapter of tree.value) {
    const matchChapter =
      chapter.chapter_no.toLowerCase().includes(keyword) ||
      chapter.title.toLowerCase().includes(keyword)
    const matchedChildren = chapter.children?.filter(
      (section) =>
        section.chapter_no.toLowerCase().includes(keyword) ||
        section.title.toLowerCase().includes(keyword),
    )
    if (matchChapter || (matchedChildren && matchedChildren.length > 0)) {
      filtered.push({
        ...chapter,
        children: matchChapter ? chapter.children : matchedChildren,
      })
    }
  }
  return filtered
})

/** 总章节数 */
const totalCount = computed(() => {
  let count = 0
  tree.value.forEach((chapter) => {
    count++
    if (chapter.children?.length) count += chapter.children.length
  })
  return count
})

/** 是否当前章节 */
const isActive = (chapterNo: string): boolean => chapterNo === props.currentChapterNo

/** 切换展开/折叠 */
const toggleExpand = (chapterNo: string) => {
  if (expandedSet.value.has(chapterNo)) {
    expandedSet.value.delete(chapterNo)
  } else {
    expandedSet.value.add(chapterNo)
  }
  expandedSet.value = new Set(expandedSet.value)
}

/**
 * 导航到章节：
 * - 聚合章行（无分工记录但展开为子节，id 为空）：点击切换展开/折叠，不跳转
 * - 真实章节（章级分工或子节分工）：跳转编辑器
 */
const handleNavigate = (chapter: NavChapter) => {
  if (!chapter.id && chapter.children?.length) {
    toggleExpand(chapter.chapter_no)
    return
  }
  if (chapter.chapter_no === props.currentChapterNo) return
  emit('navigate', chapter.chapter_no)
  router.push({
    name: 'ChapterEditor',
    params: { projectId: props.projectId, chapterNo: chapter.chapter_no },
  })
}

onMounted(() => {
  loadData()
})

watch(
  () => props.projectId,
  () => {
    loadData()
  },
)
</script>

<style scoped>
.chapter-nav {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--bg-elevated, #1f1f1f);
  border-right: 1px solid var(--border-color, #303030);
}

.chapter-nav__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-color, #303030);
  flex-shrink: 0;
}

.chapter-nav__title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary, #fff);
}

.chapter-nav__search {
  padding: 8px 12px;
  flex-shrink: 0;
}

.chapter-nav__tree {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}

.chapter-nav__empty {
  padding: 24px 16px;
  text-align: center;
}

/* 章级 */
.chapter-nav__chapter {
  margin-bottom: 2px;
}

.chapter-nav__chapter-head {
  display: flex;
  align-items: center;
  padding: 6px 12px;
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.15s;
  gap: 4px;
}

.chapter-nav__chapter-head:hover {
  background: var(--bg-hover, #2a2a2a);
}

.chapter-nav__chapter-head--active {
  background: var(--primary-color-opacity, rgba(24, 144, 255, 0.15));
  border-left: 3px solid var(--primary-color, #1890ff);
  padding-left: 9px;
}

.chapter-nav__expand {
  width: 16px;
  flex-shrink: 0;
  color: var(--text-secondary, #999);
  font-size: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.chapter-nav__chapter-no {
  font-size: 12px;
  font-weight: 600;
  color: var(--primary-color, #1890ff);
  flex-shrink: 0;
  min-width: 24px;
}

.chapter-nav__chapter-title {
  flex: 1;
  font-size: 13px;
  color: var(--text-primary, #fff);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

/* 节级 */
.chapter-nav__sections {
  padding-left: 20px;
}

.chapter-nav__section {
  display: flex;
  align-items: center;
  padding: 5px 12px 5px 8px;
  cursor: pointer;
  border-radius: 4px;
  transition: background 0.15s;
  gap: 6px;
}

.chapter-nav__section:hover {
  background: var(--bg-hover, #2a2a2a);
}

.chapter-nav__section--active {
  background: var(--primary-color-opacity, rgba(24, 144, 255, 0.15));
  border-left: 3px solid var(--primary-color, #1890ff);
  padding-left: 5px;
}

.chapter-nav__section-no {
  font-size: 11px;
  color: var(--text-secondary, #999);
  flex-shrink: 0;
  min-width: 28px;
}

.chapter-nav__section-title {
  flex: 1;
  font-size: 12px;
  color: var(--text-secondary, #ccc);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

/* 状态标签 */
.chapter-nav__status-tag {
  flex-shrink: 0;
  font-size: 10px;
  line-height: 16px;
  padding: 0 4px;
}

.chapter-nav__status-tag--small {
  font-size: 9px;
  line-height: 14px;
}

/* 底部统计 */
.chapter-nav__footer {
  padding: 8px 16px;
  border-top: 1px solid var(--border-color, #303030);
  flex-shrink: 0;
}

.chapter-nav__count {
  font-size: 11px;
  color: var(--text-tertiary, #666);
}

/* 滚动条样式 */
.chapter-nav__tree::-webkit-scrollbar {
  width: 6px;
}

.chapter-nav__tree::-webkit-scrollbar-thumb {
  background: var(--scrollbar-thumb, #444);
  border-radius: 3px;
}

.chapter-nav__tree::-webkit-scrollbar-track {
  background: transparent;
}
</style>
