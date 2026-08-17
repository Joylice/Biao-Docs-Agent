<template>
  <div
    class="markdown-renderer"
    v-html="rendered"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'

const props = withDefaults(defineProps<{ source: string }>(), {
  source: '',
})

// 安全渲染：html:false 禁用原始 HTML 直通，防 XSS；linkify 自动识别链接
const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})

const rendered = computed(() => md.render(props.source))
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
</style>
