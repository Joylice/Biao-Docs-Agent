/**
 * 版本历史管理 composable
 * - 自动快照（基于保存事件）
 * - 手动保存版本
 * - 版本列表（最多保留 20 个）
 * - 版本对比（简单文本差异）
 * - 版本恢复
 * - 本地存储（localStorage）
 */
import { ref, computed } from 'vue'

/** 版本 */
export interface Version {
  id: string
  /** 版本号（从 1 开始递增） */
  versionNumber: number
  /** 内容 HTML */
  content: string
  /** 内容 Markdown（可选） */
  markdown?: string
  /** 创建时间 */
  createdAt: number
  /** 创建者 */
  author: string
  /** 备注（手动保存时填写） */
  note?: string
  /** 是否自动保存 */
  isAuto: boolean
  /** 字数统计 */
  wordCount: number
}

/** 差异类型 */
export interface DiffSegment {
  type: 'equal' | 'add' | 'remove'
  text: string
}

/** 生成唯一 ID */
function generateId(): string {
  return `version-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}

/** 计算字数 */
function countWords(html: string): number {
  // 移除 HTML 标签后统计字符数
  const text = html.replace(/<[^>]*>/g, '').replace(/\s+/g, '')
  return text.length
}

/**
 * 简单的文本差异算法（基于行的 LCS）
 */
function computeDiff(oldText: string, newText: string): DiffSegment[] {
  const oldLines = oldText.split('\n')
  const newLines = newText.split('\n')

  const result: DiffSegment[] = []
  let i = 0
  let j = 0

  while (i < oldLines.length || j < newLines.length) {
    if (i < oldLines.length && j < newLines.length && oldLines[i] === newLines[j]) {
      result.push({ type: 'equal', text: oldLines[i] })
      i++
      j++
    } else {
      // 查找下一个匹配行
      let found = false
      for (let k = j + 1; k < Math.min(j + 5, newLines.length); k++) {
        if (i < oldLines.length && oldLines[i] === newLines[k]) {
          // j 到 k-1 是新增
          for (let m = j; m < k; m++) {
            result.push({ type: 'add', text: newLines[m] })
          }
          j = k
          found = true
          break
        }
      }
      if (!found) {
        for (let k = i + 1; k < Math.min(i + 5, oldLines.length); k++) {
          if (j < newLines.length && oldLines[k] === newLines[j]) {
            // i 到 k-1 是删除
            for (let m = i; m < k; m++) {
              result.push({ type: 'remove', text: oldLines[m] })
            }
            i = k
            found = true
            break
          }
        }
      }
      if (!found) {
        if (i < oldLines.length) {
          result.push({ type: 'remove', text: oldLines[i] })
          i++
        }
        if (j < newLines.length) {
          result.push({ type: 'add', text: newLines[j] })
          j++
        }
      }
    }
  }

  return result
}

/**
 * 使用版本历史管理
 * @param storageKey 本地存储 key
 * @param maxVersions 最大版本数（默认 20）
 */
export function useVersionHistory(storageKey = 'editor-versions', maxVersions = 20) {
  /* 版本列表（按时间倒序） */
  const versions = ref<Version[]>([])

  /* 当前选中的版本 ID（用于对比） */
  const selectedVersionId = ref<string | null>(null)

  /* 从本地存储加载 */
  const loadFromStorage = () => {
    try {
      const stored = localStorage.getItem(storageKey)
      if (stored) {
        versions.value = JSON.parse(stored)
      }
    } catch {
      // 忽略加载错误
    }
  }

  /* 保存到本地存储 */
  const saveToStorage = () => {
    try {
      // 只保存最近 maxVersions 个版本
      const toSave = versions.value.slice(0, maxVersions)
      localStorage.setItem(storageKey, JSON.stringify(toSave))
    } catch (e) {
      // 存储空间不足时，删除旧版本
      if (e instanceof Error && e.name === 'QuotaExceededError') {
        versions.value = versions.value.slice(0, Math.floor(maxVersions / 2))
        try {
          localStorage.setItem(storageKey, JSON.stringify(versions.value))
        } catch {
          // 忽略
        }
      }
    }
  }

  /* 初始化加载 */
  loadFromStorage()

  /* 下一个版本号 */
  const nextVersionNumber = computed(() => {
    if (versions.value.length === 0) return 1
    return Math.max(...versions.value.map((v) => v.versionNumber)) + 1
  })

  /**
   * 保存版本
   * @param content HTML 内容
   * @param options 选项（备注、是否自动、作者、markdown）
   */
  const saveVersion = (
    content: string,
    options: { note?: string; isAuto?: boolean; author?: string; markdown?: string } = {},
  ): Version => {
    const version: Version = {
      id: generateId(),
      versionNumber: nextVersionNumber.value,
      content,
      markdown: options.markdown,
      createdAt: Date.now(),
      author: options.author ?? '当前用户',
      note: options.note,
      isAuto: options.isAuto ?? false,
      wordCount: countWords(content),
    }

    versions.value.unshift(version)

    // 超过最大版本数时删除最旧的
    if (versions.value.length > maxVersions) {
      versions.value = versions.value.slice(0, maxVersions)
    }

    saveToStorage()
    return version
  }

  /**
   * 自动保存版本（与上一个版本内容不同时才保存）
   */
  const autoSave = (content: string, markdown?: string): Version | null => {
    // 检查与最近一个自动保存版本是否相同
    const lastAuto = versions.value.find((v) => v.isAuto)
    if (lastAuto && lastAuto.content === content) {
      return null
    }
    return saveVersion(content, { isAuto: true, markdown })
  }

  /**
   * 获取版本
   */
  const getVersion = (id: string): Version | undefined => {
    return versions.value.find((v) => v.id === id)
  }

  /**
   * 删除版本
   */
  const deleteVersion = (id: string) => {
    const index = versions.value.findIndex((v) => v.id === id)
    if (index !== -1) {
      versions.value.splice(index, 1)
      if (selectedVersionId.value === id) {
        selectedVersionId.value = null
      }
      saveToStorage()
    }
  }

  /**
   * 重命名版本（修改备注）
   */
  const renameVersion = (id: string, note: string) => {
    const version = versions.value.find((v) => v.id === id)
    if (version) {
      version.note = note
      saveToStorage()
    }
  }

  /**
   * 对比两个版本
   */
  const compareVersions = (versionId1: string, versionId2: string): DiffSegment[] => {
    const v1 = getVersion(versionId1)
    const v2 = getVersion(versionId2)
    if (!v1 || !v2) return []
    return computeDiff(v1.content, v2.content)
  }

  /**
   * 对比版本与当前内容
   */
  const compareWithCurrent = (versionId: string, currentContent: string): DiffSegment[] => {
    const version = getVersion(versionId)
    if (!version) return []
    return computeDiff(version.content, currentContent)
  }

  /**
   * 清空所有版本
   */
  const clearAll = () => {
    versions.value = []
    selectedVersionId.value = null
    localStorage.removeItem(storageKey)
  }

  /**
   * 格式化时间
   */
  const formatTime = (timestamp: number): string => {
    const date = new Date(timestamp)
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
  }

  return {
    // 状态
    versions,
    selectedVersionId,
    nextVersionNumber,
    // 操作
    saveVersion,
    autoSave,
    getVersion,
    deleteVersion,
    renameVersion,
    compareVersions,
    compareWithCurrent,
    clearAll,
    formatTime,
  }
}
