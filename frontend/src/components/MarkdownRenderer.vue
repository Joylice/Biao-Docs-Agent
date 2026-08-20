<template>
  <div
    class="markdown-renderer"
    v-html="rendered"
  />
</template>

<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import MarkdownIt from 'markdown-it'
import api from '@/api/client'

const props = withDefaults(defineProps<{ source: string; projectId?: string }>(), {
  source: '',
  projectId: '',
})

// 安全渲染：html:false 禁用原始 HTML 直通，防 XSS；linkify 自动识别链接
const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

// ── 章节插图解析（阶段 2）──
// <img> 标签无法携带 JWT，正文中的代理路径/旧内网签名 URL 需换成公共可读的签名 URL；
// 旧数据兼容：http://minio:9000 内网地址浏览器不可达，按 storage_key 重新签名。
const signedUrls = reactive(new Map<string, string>())
const resolvingKeys = new Set<string>()

// 新格式：/api/v1/projects/{pid}/images/view?key={storage_key}
const PROXY_RE = /\/api\/v1\/projects\/([\w-]+)\/images\/view\?key=([^)")\s]+)/g
// 旧格式：http://minio:9000/{bucket}/{storage_key}?...（内网 host，签名不可复用）
const LEGACY_RE = /http:\/\/minio:9000\/[^/]+\/([^?)(")\s]+)/g

function collectImageKeys(src: string): { pid: string; key: string }[] {
  const found: { pid: string; key: string }[] = []
  for (const m of src.matchAll(PROXY_RE)) {
    found.push({ pid: m[1], key: decodeURIComponent(m[2]) })
  }
  for (const m of src.matchAll(LEGACY_RE)) {
    const key = decodeURIComponent(m[1])
    // 仅能解析本项目 images 目录的旧图（跨项目 key 后端会拒绝）
    if (props.projectId && key.startsWith(`images/${props.projectId}/`)) {
      found.push({ pid: props.projectId, key })
    }
  }
  return found
}

async function resolveSignedUrl(pid: string, key: string): Promise<void> {
  if (signedUrls.has(key) || resolvingKeys.has(key)) return
  resolvingKeys.add(key)
  try {
    const { data } = await api.get(`/projects/${pid}/images/signed`, {
      params: { storage_key: key },
    })
    if (data.code === 0 && data.data?.url) {
      signedUrls.set(key, data.data.url)
    }
  } catch {
    // 签名失败保持占位，不阻断正文渲染
  } finally {
    resolvingKeys.delete(key)
  }
}

watch(
  () => [props.source, props.projectId],
  () => {
    for (const { pid, key } of collectImageKeys(props.source)) {
      void resolveSignedUrl(pid, key)
    }
  },
  { immediate: true },
)

const rendered = computed(() => {
  let text = props.source
  // 代理路径 → 签名 URL（未就绪时保留占位，签名到达后响应式重渲染）
  text = text.replace(PROXY_RE, (match, _pid, key) => signedUrls.get(decodeURIComponent(key)) || match)
  // 旧内网签名 URL → 重签名 URL
  text = text.replace(LEGACY_RE, (match, key) => signedUrls.get(decodeURIComponent(key)) || match)
  return md.render(text)
})
</script>

<style scoped>
.markdown-renderer {
  font-size: 14px;
  line-height: 1.8;
  color: var(--text-primary);
  word-break: break-word;
}

.markdown-renderer :deep(h1),
.markdown-renderer :deep(h2),
.markdown-renderer :deep(h3),
.markdown-renderer :deep(h4) {
  margin: 1em 0 0.5em;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.4;
}

.markdown-renderer :deep(h1) {
  font-size: 20px;
  border-bottom: 1px solid var(--border-color);
  padding-bottom: 8px;
}

.markdown-renderer :deep(h2) {
  font-size: 17px;
}

.markdown-renderer :deep(h3) {
  font-size: 15px;
}

.markdown-renderer :deep(h4) {
  font-size: 14px;
}

.markdown-renderer :deep(p) {
  margin: 0.5em 0;
}

.markdown-renderer :deep(ul),
.markdown-renderer :deep(ol) {
  padding-left: 1.6em;
  margin: 0.5em 0;
}

.markdown-renderer :deep(li) {
  margin: 0.25em 0;
}

.markdown-renderer :deep(blockquote) {
  margin: 0.8em 0;
  padding: 4px 12px;
  border-left: 3px solid var(--color-primary);
  background: var(--bg-block);
  color: var(--text-secondary);
  border-radius: 2px;
}

.markdown-renderer :deep(code) {
  padding: 2px 6px;
  background: var(--bg-block);
  border-radius: 4px;
  font-size: 13px;
  font-family: 'Consolas', 'Courier New', monospace;
}

.markdown-renderer :deep(pre) {
  padding: 12px 16px;
  background: var(--bg-block);
  border-radius: 6px;
  overflow-x: auto;
}

.markdown-renderer :deep(pre code) {
  padding: 0;
  background: transparent;
}

.markdown-renderer :deep(table) {
  width: 100%;
  border-collapse: collapse;
  margin: 0.8em 0;
}

.markdown-renderer :deep(th),
.markdown-renderer :deep(td) {
  border: 1px solid var(--border-color);
  padding: 8px 12px;
  text-align: left;
}

.markdown-renderer :deep(th) {
  background: var(--bg-block);
  font-weight: 600;
}

.markdown-renderer :deep(a) {
  color: var(--color-primary);
}

.markdown-renderer :deep(hr) {
  border: none;
  border-top: 1px solid var(--border-color);
  margin: 1em 0;
}

.markdown-renderer :deep(img) {
  max-width: 100%;
  border-radius: 4px;
}
</style>
