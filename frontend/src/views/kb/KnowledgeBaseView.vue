<template>
  <div>
    <a-page-header title="资料库" sub-title="上传与管理公司资料（产品手册/历史方案/资质证书）" />
    <a-upload-dragger :multiple="true" action="/api/v1/documents/upload" name="file">
      <p class="ant-upload-drag-icon">
        <span style="font-size: 48px">&#128196;</span>
      </p>
      <p class="ant-upload-text">点击或拖拽文件到此区域上传</p>
      <p class="ant-upload-hint">支持 PDF、Word 格式，单文件不超过 50MB</p>
    </a-upload-dragger>
    <a-divider />
    <a-empty description="暂无资料（功能开发中）" />
  </div>
</template>

<script setup lang="ts">
// 资料库页面 — 阶段 2 实现完整功能
</script>
