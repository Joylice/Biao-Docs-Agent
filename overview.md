# 交付总结：模型配置中心弹窗化重构（2026-09-10）

## TL;DR

参考 AllDocMind（OpenMAIC 风格）将内嵌设置页重构为弹出式配置中心：左侧两级导航 6 分类，同时完成后端 key 真源统一（llm_providers 唯一真源），全量回归通过（前端 279 tests / 后端 1203 tests，0 failed）。

## 交付概览

| 项 | 状态 |
|---|---|
| 交付状态 | ✅ 全部完成（7 个 commit，本地 master） |
| 前端测试 | 279 passed / 0 failed（vue-tsc + vitest + vite build 全绿） |
| 后端测试 | 1203 passed / 5 skipped / 0 failed |
| 已知问题 | ① 7 个 commit 未 push（含基线快照 46b87f2，推送前需确认）② 仓库根 2 个无害临时文件（safe-delete 拦截删除） |

## 功能清单（6 分类弹窗）

| 分类 | 内容 |
|---|---|
| 配置概览（新增） | 3 提供方 key 状态 / 8 阶段路由 / embedding·rerank / 外部工具状态卡，点击跳转，保存驱动刷新 |
| 语言模型 | 自定义端点 / DeepSeek / 智谱 GLM 三条目（掩码 key + api_base + 测试连接）+ 阶段路由（8 阶段模型/参数） |
| 知识库参数 | embedding 配置 + recall_top_k/similarity_threshold/hybrid_weight + rerank + 重建索引 |
| 网络搜索 | Tavily / Brave / SearXNG 每 preset 一条目（乐观锁 + 阶段绑定） |
| 技能 | 流水线阶段视图：启停 + 工具绑定 |
| 系统设置 | mock 开关、审计日志、LLM 用量 |

后端：llm_providers 成为唯一 API key 真源（修复"连通性测试正常但解析失败"的双真源缺陷）；三态密钥契约全链路对齐（留空=保持/显式清除=空串/掩码串拒传）。

## Commit 清单（本地 master，未 push）

| commit | 内容 |
|---|---|
| 46b87f2 | 基线快照（修复 git 对象库损坏期间仅存工作区的历史工作） |
| d4c028e | R1 后端 key 真源统一（TDD） |
| 0f2c9ba | QA 边界用例 ×8 |
| 8f92b66 | T01 弹窗基础设施 |
| e857522 | T02 语言模型分类 |
| ff87793 | T03 知识库参数 + 系统设置 |
| 9768ee8 | T04 概览 + 网络搜索 + 技能 |
| （T05） | 旧设置视图下线（6 文件 git rm） |

## 过程事故记录

T05 执行 git rm 时 safe-delete shim 误将 frontend/src 全目录（222 文件）从工作区删除——已用 `git restore frontend/src` 从 HEAD 全量恢复，零丢失。教训已记入工作日志。

## 下一步建议

1. 浏览器验证：启动系统（uvicorn + vite dev）→ 顶栏"模型设置" → 走查 6 分类配置流
2. 确认后统一 push（7 个 commit，含较大的基线快照）
3. 择期清理仓库根 2 个临时文件与 frontend/ 下的 dist-verify* 目录
