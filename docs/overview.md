# 架构分层治理重构完成（全 Phase 交付）

## 交付时间
2026-08-31

## 重构范围

| Phase | 状态 | 核心动作 | 风险 |
|---|---|---|---|
| **1. 工具函数提取** | ✅ | `natural_sort_key`/`numbered_sections` → `core/sorting.py`；`markdown-converter` → `utils/`；`SaveStatus` → `types/editor.ts`；消除 division_service 伪耦合 | 低 |
| **2. API层LLM收敛** | ✅ | `division.py` 的 `call_llm_text` 直连 → 封装到 `assist_service.assist_selection()`；提示词模板移入 service 层；`db.commit()` 评估后保持现状（合法 Unit-of-Work 模式） | 中 |
| **3. 上帝模块拆分** | ✅ | `workflow_runtime.py` 755行 → 4个文件（344+274+75+93），re-export 保持 API 层兼容 | 高 |
| **4. Agents层解耦** | ✅ | `_shared.py` 的 3 个 DB 操作函数迁入 service 层（`workflow_metadata_service` + `chapter_service`），agents 不再直接操作 ORM | 中高 |
| **5. 前端分层** | ✅ | composable 拆分（Persistence/AiAssistant/TaskWorkflow）+ Toolbar/ReviewView 大组件拆分（见下） | 中 |

### Phase 5 明细

| 子项 | 状态 | 动作 |
|---|---|---|
| 5.1 `useChapterPersistence` (265行) | ✅ | 拆为 `useChapterLoader`(118) + `useChapterSave`(107)，原文件变 50 行编排层 |
| 5.2 `useAiAssistant` (264行) | ✅ | 拆为 `useAssistSelection` + `useAssistChapter`，原文件变 45 行编排层 |
| 5.3 `WordEditorPage` (1462行) | ✅ | 任务状态机抽为 `useTaskWorkflow`(169)，-180行 |
| 5.4 `WordEditorToolbar` (1242行) | ✅ | 按 Ribbon 选项卡拆为 4 个子组件 + `useEditorCommands`(共享命令)，父组件剩 94 行骨架 |
| 5.5 `ReviewView` (1143行) | ✅ | 编排逻辑抽为 `useReviewState`/`useReviewActions`/`useReviewNavigation`，文件降至 923 行；修复遗留未使用变量 `submitters`(TS6133) |

## 新建文件清单

### 后端（6个）
| 文件 | 行数 | 职责 |
|---|---|---|
| `app/core/sorting.py` | 42 | 章节编号排序与子节编号（跨域共享） |
| `app/services/infra/workflow_content_service.py` | 274 | 章节内容操作（编辑/回写/初稿/导出） |
| `app/services/infra/workflow_outline_service.py` | 75 | 大纲草稿管理 |
| `app/services/infra/workflow_feedback_service.py` | 93 | 成员收集 + 审阅意见回派 |
| `app/services/infra/workflow_metadata_service.py` | 76 | 工作流元数据 CRUD |
| `deploy/docker-compose.prod.yml` + `.env.prod` | — | 目标服务器 192.168.18.200 生产部署适配（端口重映射/生产密钥/生产模式） |

### 前端（14个）
| 文件 | 职责 |
|---|---|
| `types/editor.ts` | 编辑器共享类型 |
| `utils/markdown-converter.ts` | Markdown↔HTML 转换（公共层） |
| `composables/useChapterLoader.ts` / `useChapterSave.ts` | 章节加载 / 保存状态机 |
| `composables/useTaskWorkflow.ts` | 任务状态机 |
| `composables/useAssistSelection.ts` / `useAssistChapter.ts` | 选区辅助 / 整章辅助 |
| `components/editor/toolbar/useEditorCommands.ts` | 工具栏共享 editor 命令 |
| `components/editor/toolbar/ToolbarHomeTab.vue` (489) | 「开始」选项卡 |
| `components/editor/toolbar/ToolbarInsertTab.vue` (272) | 「插入」选项卡 |
| `components/editor/toolbar/ToolbarLayoutTab.vue` (192) | 「布局」选项卡 |
| `components/editor/toolbar/ToolbarViewTab.vue` (126) | 「视图」选项卡 |
| `views/review/composables/useReviewState.ts` / `useReviewActions.ts` / `useReviewNavigation.ts` | 审阅状态 / 动作 / 导航 |

## 修改文件（19个）

后端：`export_service` / `chapter_service` / `division_service` / `workflow_runtime`(344行,-411) / `assist_service` / `division.py` / `agents/nodes/_shared.py` / `tests/test_chapter_split.py`
前端：`WordEditorStatusBar` / `useChapterPersistence`(50行) / `useAiAssistant`(45行) / `WordEditorPage` / `WordEditorToolbar`(94行) / `WordEditorVersionHistory` / `markdown-converter` / `ChapterPreview` / `ReviewView`(923行) / `project.ts` / `components.d.ts`

## 验证结果

- ✅ 后端 11 个修改文件语法全部通过（Python AST 解析）
- ✅ 前端 vue-tsc **0 错误**（含 5.5 修复后）
- ✅ **`vite build` 生产构建成功**（8.49s，WordEditorPage chunk 120KB / ReviewView 44KB）
- ✅ 旧引用残留 0 个
- ✅ `core.sorting` 功能断言通过
- ✅ **Phase 1-5 全部完成**，原始未完成清单清零

## 部署适配（192.168.18.200，1Panel v1.10.31-lts）

服务器实况（面板 API 只读评估）：Ubuntu / kernel 6.8 / amd64 / Docker 运行中（已有 66 容器） / 磁盘 ~3.3TB / 面板监控未启用（内存余量需登录确认）。

端口冲突与重映射（`deploy/docker-compose.prod.yml`）：

| 服务 | 默认端口 | 服务器占用 | 生产映射 |
|---|---|---|---|
| postgres | 5432 | 空闲 | `15432:5432` |
| redis | 6379 | autoconvert_redis | `16379:6379` |
| minio | 9000/9001 | autoconvert_minio(9000,9090) | `19000:9000` `19001:9001` |
| api | 8000 | 流量网关 FastAPI | `18000:8000` |
| web | 5173 | 空闲 | `5173:80` |

生产模式差异：去源码挂载/`--reload`、`BID_DEBUG=false`、`restart: unless-stopped`、注入 `BID_JWT_SECRET`/`BID_MINIO_SECRET_KEY`（`validate_runtime_secrets` 要求）、`BID_MINIO_PUBLIC_ENDPOINT=192.168.18.200:19000`、CORS 指向 `http://192.168.18.200:5173`。

部署命令：`docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build`

## 部署执行结果（2026-08-31 晚间，已上线）

目标服务器 **192.168.18.200 部署成功**（6 容器全部 running）：

| 服务 | 容器 | 端口 | 状态 |
|---|---|---|---|
| 前端 | deploy-web-1 | 5173 | ✅ 200 |
| 后端 API | deploy-api-1 | 18000 | ✅ `/health` → `{"status":"ok"}` |
| Arq Worker | deploy-worker-1 | — | ✅ running |
| PostgreSQL+pgvector | deploy-postgres-1 | 15432 | ✅ running |
| Redis | deploy-redis-1 | 16379 | ✅ running |
| MinIO | deploy-minio-1 | 19000/19001 | ✅ running |

**访问**：前端 http://192.168.18.200:5173 ｜ API http://192.168.18.200:18000/docs

**部署路径（离线镜像方案）**：本地构建（bidagent-backend/web）→ docker save 导出（infra 223MB + app 531MB）→ 1Panel 文件上传 → `containers/image/load` → compose 编排 up。

**排障记录（连环 5 坑）**：
1. 服务器 dockerd 无法访问外网镜像仓库（docker hub / 1ms.run 均不可达）→ 改离线镜像方案
2. 1Panel `files/upload` 的 `path` 是**目录语义**（文件名取原始名）→ 目标路径为目录而非文件
3. 1Panel `newComposeEnv` 写 `1panel.env`，但 docker-compose `${VAR}` 替换只读同目录 **`.env`** → 密钥全空，api 被 `validate_runtime_secrets` 拒启（worker 不走 lifespan 未受影响）
4. `alembic_version.version_num` varchar(32) 存不下 35 字符 revision `0016_annotation_edit_version_rollback` → 一次性迁移容器预建 varchar(128) 版本表后 `alembic upgrade head` 全链通过
5. api `command` 前置 `alembic upgrade head`（幂等），重启自愈

**线上运维要点**：改配置后经 1Panel「容器编排」重新 `up`（复用容器）；升级版本 = 本地重新构建 + save + load + compose up；密钥在 `/opt/bidagent/deploy/.env` 与 `1panel.env`。

## 测试环境迭代部署工具包（2026-08-31 晚，commit 1b4e895）

解决"下次迭代部署"自动化问题，新增 5 文件：

| 文件 | 职责 |
|---|---|
| `deploy/deploy-remote.ps1` | 一键迭代部署（构建→save→gzip→上传→load→retag→compose up→健康检查） |
| `deploy/panel_api.py` | 1Panel API 客户端（API Key / Session 双认证，upload/load/tag/compose 封装） |
| `deploy/REMOTE-DEPLOY.md` | 操作手册（首次/迭代/回滚/FAQ，沉淀 5 坑） |
| `deploy/.env.remote` + `.example` | 远端连接参数（已 gitignore，含面板地址/入口/账号/API Key/Cookie） |

**使用**：
```powershell
powershell -ExecutionPolicy Bypass -File deploy\deploy-remote.ps1            # 日常迭代
powershell -ExecutionPolicy Bypass -File deploy\deploy-remote.ps1 -InitInfra # 首次部署
powershell -ExecutionPolicy Bypass -File deploy\deploy-remote.ps1 -HealthOnly
```

**关键设计**：镜像版本化 tag（默认 yyyyMMdd，服务器保留历史 tag 可回滚）；`compose-test` 对已存在编排会报"记录已存在"（1Panel 限制，脚本降级跳过）；`compose-up` 幂等可重复。

**验证**：ps1 语法 0 错误；`-HealthOnly` 实测通过（API + Web OK）；`panel_api.py` 实测 health-check/containers/compose-search/compose-test 全通过（修复 `_request` 漏带认证头的 bug）。

## 技术债务清理

- ✅ `store.isOwner` 占位死代码删除
- ✅ `useChapterPersistence` 对 component 层依赖消除
- ✅ `division_service` 伪耦合消除
- ✅ `ReviewView` 未使用变量（TS6133）修复

## 关键决策

1. **`db.commit()` 保持现状**：API 层仅做事务边界管理，无直接 DB 操作，属合法 Unit-of-Work-per-Request 模式
2. **Re-export 策略**：后端拆分保持向后兼容，调用方零改动
3. **前端 computed getter**：`useAiAssistant` loading getter 改为 computed boolean，兼容 ant-design `:loading`
4. **生产部署独立 compose**：`docker-compose.prod.yml` 与本地开发配置隔离，避免端口/模式互相干扰

## 2026-08-31 增量：模型配置页追加 API Key（已发版测试环境）

**功能**：
- **LLM 服务 API Key**（`llm_api_key`）：`llm_api_base` 指向的私有化端点专用密钥——带 token 的 vLLM 网关/企业大模型中台可在页面配置凭据；安全约束：仅用于自定义端点，绝不回退/透传 DeepSeek/百炼云端密钥
- **4 家主流提供商密钥**：OpenAI / Anthropic / 智谱 / 月之暗面，按模型前缀自动匹配
- 三态契约（None=保持 / 空串=清除 / 非空=更新）、脱敏回显（`sk-****3456`）、疑似脱敏串拒收（S-1）、Fernet 加密入库

**迁移**：`0022_llm_api_key` + `0023_extra_provider_keys`（api 启动自动 `alembic upgrade head`，幂等）

**发版**：`deploy-remote.ps1 -Version 20260831` → commit `588b042`（8 文件，402 insertions）已推送

**发版踩坑（已修复 panel_api.py 并入库）**：
1. 1Panel `image/load` 偶发 `SQLITE_BUSY`（面板 SQLite 瞬态锁）→ 重试收敛（3 次，间隔 8s）
2. `image/tag` / `compose-up` 同样可能 BUSY → 各加重试
3. 大镜像包 load 超过 30s 读超时 → 读超时放宽至 900s
4. **compose up 只比较镜像 tag 不比较 digest**：服务器已有旧 `latest` 时容器不会重建 → 需先删除 api/web 容器再编排 up（已实测）

**验证结果**（192.168.18.200）：
- 6 容器全部 running；`/health` → `{"status":"ok"}`；前端 200
- API Key 三态闭环：写入 `sk-test-llm-key-123456` → 脱敏回显 `sk-****3456` → 拒收 `sk-****3456` → 空串清除 → configured=False ✅
- 后端回归 540 passed；前端 `vue-tsc + vite build` 通过

## 2026-08-31 增量 2：第二轮发版 v20260901 + 发版脚本一键化（commit 5f7db08 / efa558c）

**第二轮发版（v20260901，commit 5f7db08）**：
- `_PROVIDER_ALIASES` 别名映射：zhipu/glm/moonshot/kimi/deepseek 自动转 litellm `openai/` 前缀 + 默认 api_base（用户自定义端点优先）
- ParseView 解析进度提示 / 可折叠文件列表 / 重新解析按钮（15min 超时标记）；documents.ts `reparseTenderDocument`
- 修复并行改动 4 处 TS 类型错误（isStale 参数放宽兼容表格 record）
- 验证：bundle hash 与本地新构建一致（容器已重建）；zhipu alias 实测命中智谱端点（AuthenticationError 验证）；恢复 qwen72b 连通 712ms

**发版脚本一键化（commit efa558c）**：
- 修复 compose-test 降级逻辑：1Panel 中文消息经管道 GBK 乱码致关键字匹配失效 → 改为 compose-search 先查记录，存在即跳过 test
- panel_api.py 已内建 load/tag/compose-up 的 SQLITE_BUSY 重试 + 900s 读超时（上一轮）
- 实测 `-SkipBuild` 全流程 EXIT=0，6 容器 + 健康检查通过 —— 日常迭代发版一条命令完成

**LLM 端点（已配置生效）**：`qwen72b` + `http://123.249.37.244:7778/v1`（MindIE Server），连通测试 712ms；Embedding 待配置

**运维速查**：
- 日常发版：`deploy\deploy-remote.ps1`（自动构建/上传/加载/retag/编排/健康检查，全幂等）
- 回滚：`python deploy\panel_api.py tag bidagent-backend:20260831 bidagent-backend:latest` → 编排 up
- 手册：`deploy/REMOTE-DEPLOY.md`（FAQ 1-9 全量踩坑记录）

## 2026-08-31 增量二：LLM 配置环境变量回退 + 测试环境配置固化（已发版）

**功能**：
- `config.py` 新增 9 个 env 字段：`BID_LLM_API_BASE` / `BID_LLM_API_KEY` / 6 家提供商 key / `BID_EMBEDDING_API_KEY`
- `get_runtime_config()`：数据库无配置时从环境变量构建运行时配置（`_build_config_from_env`）——测试环境配置固化，发版无需手动设置，数据库重置后自动恢复
- compose 注入完整 env 集（api/worker），默认值：LLM `zhipu/glm-4.6v` @ 智谱、Embedding `jiaorong-bge-m3` @ `c4ai.ccccltd.cn`
- `deploy/.env.test.example`：测试环境配置模板（密钥仅存服务器 `1panel.env`，不入库）

**修复（发版前发现）**：`_build_config_from_env` 的 `has_any` 误把有非空默认值的 `llm_model`/`embedding_model` 计入 → 数据库无行时永远触发 env 回退（破坏原「无行返回 None」语义）→ 改为只检查显式端点/密钥字段（默认值均为空）。回归 540 passed。

**发版**：`deploy-remote.ps1 -Version 20260831-2` 一次跑通（BUSY 重试生效）→ commit `482c12e`（5 文件，139 insertions）已推送。

**验证**（192.168.18.200）：6 容器 running；DB 配置优先（智谱 GLM-4.6v + 智谱 key，Embedding 中咨 bge-m3）；连通性 `ok=True`，`openai/glm-4.6v` 366ms 真实调用通过。

## 2026-08-31 增量②：第二轮发版 v20260831r2（LLM 配置 env 回退 + 配置固化）

**内容**（commit `5f7db08` / `efa558c` / `482c12e`，已推送）：
- **LLM 配置环境变量回退**：compose 新增 `BID_LLM_MODEL`（默认 `zhipu/glm-4.6v` + 智谱端点）、`BID_EMBEDDING_MODEL`（默认 `jiaorong-bge-m3` + `c4ai.cccltd.cn` 内网端点）、6 家提供商密钥变量（`BID_DEEPSEEK_API_KEY` / `BID_ZHIPU_API_KEY` 等）；数据库页面配置优先于 env 回退
- **招标文件重新解析**（ParseView +120 行）+ LLM provider 别名适配
- **compose-test 迭代跳过逻辑修复**（先查记录，规避乱码编码导致的关键字匹配失效）
- 新增 `deploy/.env.test.example` 配置模板

**发版动作**：新 compose 上传服务器 → 服务器 `.env` 追加新变量（空值走默认）→ 一键发版全链路一次通过（EXIT=0）

**验证**：6 容器 running；LLM 智谱 GLM-4.6V 真实调用 **426ms**；Embedding bge-m3 **1024 维**；env 注入正确；前端 200 / 鉴权 401

**回滚**：服务器镜像 tag `bidagent-backend:20260831r2`（另有 `20260831`），一键 retag 即可

**清理**：本地构建临时目录（507MB）与服务器 `/opt/app_*.tar.gz` 已删除，镜像 tag 保留不影响回滚
