/**
 * 知识库容器数据与派生选项（阶段 1：多知识库容器，全局素材 / 项目素材切换逻辑）.
 * 素材页无项目上下文 → 后端仅返回公司库 + 本人个人库。
 */
import { computed, ref } from 'vue'
import { message } from 'ant-design-vue'
import { fetchProjects, fetchKbBases } from '@/api'
import { isKbAdmin, currentUserId } from '@/stores/currentUser'
import type { KbBase, ProjectLite } from '../constants'

export function useKbBases() {
  // 阶段 1：知识库容器状态
  const kbBases = ref<KbBase[]>([])
  const basesLoading = ref(false)
  const selectedKbId = ref<string>('')
  const companyBases = computed(() => kbBases.value.filter((b) => b.scope === 'company'))
  const projectBases = computed(() => kbBases.value.filter((b) => b.scope === 'project'))
  const personalBases = computed(() => kbBases.value.filter((b) => b.scope === 'personal'))

  // ---- 项目列表（阶段 3：项目库建库选项 + 写权限判定）----
  const myProjects = ref<ProjectLite[]>([])
  const fetchMyProjects = async () => {
    try {
      const { data } = await fetchProjects({ page: 1, page_size: 100 })
      if (data.code === 0) myProjects.value = data.data.items
    } catch {
      // 静默：项目库选项为空时建库弹窗会提示
    }
  }
  // 仅我负责的项目可建项目库（后端 create_base 同样限定 owner）
  const ownedProjectOptions = computed(() =>
    myProjects.value
      .filter((p) => p.owner_id === currentUserId.value)
      .map((p) => ({ value: p.id, label: p.name })),
  )
  const ownedProjectIds = computed(
    () => new Set(myProjects.value.filter((p) => p.owner_id === currentUserId.value).map((p) => p.id)),
  )

  // 上传可选库：个人库（后端仅返回本人）+ 项目库（仅负责人可写）+ 公司库（仅管理员可写）
  const writableBaseOptions = computed(() =>
    kbBases.value
      .filter(
        (b) =>
          b.scope === 'personal' ||
          (b.scope === 'project' && !!b.project_id && ownedProjectIds.value.has(b.project_id)) ||
          (b.scope === 'company' && isKbAdmin.value),
      )
      .map((b) => ({
        value: b.id,
        label:
          b.scope === 'project'
            ? `${b.name}（项目·${b.project_name || ''}）`
            : `${b.name}（${b.scope === 'company' ? '公司' : '个人'}）`,
      })),
  )
  const selectedBase = computed(() => kbBases.value.find((b) => b.id === selectedKbId.value))
  const canDeleteSelectedBase = computed(() => {
    const base = kbBases.value.find((b) => b.id === selectedKbId.value)
    if (!base) return false
    if (base.scope === 'personal') return true
    if (base.scope === 'project') {
      return !!base.project_id && ownedProjectIds.value.has(base.project_id)
    }
    return isKbAdmin.value
  })

  // 个人/项目库选项（排除公司库，用于从公司库选取时的目标库）
  const personalProjectBaseOptions = computed(() =>
    kbBases.value
      .filter((b) => b.scope !== 'company')
      .map((b) => ({
        value: b.id,
        label:
          b.scope === 'project'
            ? `${b.name}（项目·${b.project_name || ''}）`
            : `${b.name}（个人）`,
      })),
  )

  const fetchBases = async () => {
    basesLoading.value = true
    try {
      const { data } = await fetchKbBases()
      if (data.code === 0) kbBases.value = data.data.items
    } catch {
      message.error('加载知识库失败')
    } finally {
      basesLoading.value = false
    }
  }

  return {
    kbBases,
    basesLoading,
    selectedKbId,
    companyBases,
    projectBases,
    personalBases,
    fetchMyProjects,
    ownedProjectOptions,
    writableBaseOptions,
    personalProjectBaseOptions,
    selectedBase,
    canDeleteSelectedBase,
    fetchBases,
  }
}
