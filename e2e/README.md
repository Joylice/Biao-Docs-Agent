# e2e — Playwright 全链路回归测试

投标智能体 6 大核心 E2E 场景（定义见 `docs/agents/testing.md §4` 与 `.qoder/agents/e2e-tester.md`）：

| spec 文件 | 覆盖场景 |
|---|---|
| `tests/auth.spec.ts` | 场景1/E2E-01：注册 → 登录拿 JWT → /auth/me → （刷新 token）→ UI 登录进入工作台 |
| `tests/projects.spec.ts` | 场景2/E2E-07：创建项目 → 添加成员 → 越权访问 403、数据不泄露 |
| `tests/document-parse.spec.ts` | 场景3/E2E-02：上传招标文件 → 异步解析 → 评分点/技术需求入库 + HITL 确认 |
| `tests/kb-rag.spec.ts` | 场景4/E2E-03：上传 3 份资料 → 分块向量化 → 相似度检索命中 |
| `tests/workflow-generation.spec.ts` | 场景5/E2E-04/05/06：评分点确认 → 大纲确认 → 章节生成 → 审阅重写 → Word 导出 |
| `tests/websocket.spec.ts` | 场景6：WebSocket 连接、ping/pong、get_status 消息顺序与完整性 |

测试文件（最小 PDF/DOCX）由 `fixtures/files.ts` 以 buffer 动态生成，无需外部样例文件。

---

## 1. 启动依赖服务

E2E 依赖完整后端栈（postgres + pgvector / redis / minio / api / worker / 前端）。

```powershell
# 基础设施 + 应用（在仓库根目录）
docker compose -f deploy/docker-compose.yml up -d

# 执行数据库迁移（首次）
cd backend; .venv\Scripts\python.exe -m alembic upgrade head
```

若不用 docker compose 起 api/web，可本地分别启动：

```powershell
# 后端（8000）——注意带上 LLM mock 开关
cd backend; $env:BID_LLM_MOCK="true"; .venv\Scripts\python.exe -m uvicorn app.main:app --port 8000

# Arq worker（异步解析/向量化任务）
cd backend; arq worker.WorkerSettings

# 前端（5173）
cd frontend; npm run dev
```

## 2. 安装与运行测试

```powershell
cd e2e
npm install                 # 安装 @playwright/test
npx playwright install chromium   # 安装浏览器内核

npm test                    # 全量回归
npm run test:headed         # 有头模式
npx playwright test -g "E2E-07"   # 单场景过滤
npx playwright show-report  # 查看 HTML 报告
```

> Windows PowerShell 环境：命令分隔用 `;`，不要用 `&&`。

## 3. 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `E2E_BASE_URL` | `http://localhost:5173` | 前端地址（UI 场景 baseURL） |
| `E2E_API_URL` | `http://localhost:8000` | 后端 API 地址（API/WS 场景） |
| `BID_LLM_MOCK` | 未设置 | 后端 LLM mock 开关；`true` 时放开 LLM 相关用例 |
| `CI` | 未设置 | CI 模式下启用 forbidOnly + 1 次重试 |

示例：

```powershell
$env:E2E_API_URL="http://localhost:8000"; $env:BID_LLM_MOCK="true"; npm test
```

## 4. 跳过策略（区分"环境缺失"与"真实失败"）

- 每个 spec 的 `beforeEach` 先探测 `GET /health`，后端/基础设施不可达时整组 **skip**（非失败）；
- 前端不可达时仅 UI 用例 skip，API 契约用例照常执行；
- 文档状态轮询（`waitForDocumentStatus`）超时未推进 → skip 并附原因（worker 未运行/任务未入队）。

## 5. 已知前置条件与限制（基于当前后端实现）

1. **LLM mock 开关已在服务层生效**：`services/llm_service.py` / `rag_service.py` 已引用 `settings.llm_mock`。
   相关用例需后端以 `BID_LLM_MOCK=true` 启动，未设置时 skip。
2. **无 /auth/refresh 端点**：`auth.py` 仅 register/login/me，刷新 token 用例 skip。
3. **上传未入队异步任务**：`documents.py` 上传后不调用 arq enqueue（无解析/向量化触发端点），
   文档状态轮询不推进时对应用例 skip（附清晰原因）。
4. **无 RAG 检索端点**：`retrieve_similar` 仅存在于 service 层，检索命中用例 skip。
5. **workflow 为 TODO stub**：start/status/confirm 端点返回固定契约，章节生成/审阅/导出
   的真实闭环断言待 LangGraph checkpointer 接入后启用；当前仅断言现有 API 契约。
6. **WebSocket 无鉴权**：`/ws/{project_id}` 未校验 JWT（与后端现状一致，仅断言协议行为）。
