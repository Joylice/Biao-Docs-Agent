/** 当前项目上下文状态 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Project, ProjectMember } from '@/types'
import { fetchProject, fetchProjectMembers } from '@/api/projects'

export const useProjectStore = defineStore('project', () => {
  const currentProjectId = ref<string>('')
  const project = ref<Project | null>(null)
  const members = ref<ProjectMember[]>([])
  const loading = ref(false)
  const error = ref('')

  const memberOptions = computed(() =>
    members.value.map((m) => ({
      value: m.user_id,
      label: `${m.display_name}（${m.email}）`,
    })),
  )

  const loadProject = async (projectId: string) => {
    if (currentProjectId.value === projectId && project.value) return
    currentProjectId.value = projectId
    loading.value = true
    error.value = ''
    try {
      const { data } = await fetchProject(projectId)
      if (data.code === 0) {
        project.value = data.data
      }
    } catch {
      error.value = '项目加载失败'
    } finally {
      loading.value = false
    }
  }

  const loadMembers = async (projectId: string) => {
    try {
      const { data } = await fetchProjectMembers(projectId)
      if (data.code === 0) {
        members.value = data.data.items
      }
    } catch {
      // 成员加载失败不阻塞
    }
  }

  const clearProject = () => {
    currentProjectId.value = ''
    project.value = null
    members.value = []
    error.value = ''
  }

  return {
    currentProjectId,
    project,
    members,
    loading,
    error,
    memberOptions,
    loadProject,
    loadMembers,
    clearProject,
  }
})
