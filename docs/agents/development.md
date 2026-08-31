# development.md — 项目约定与开发规约

> 本文是 AGENTS.md 的分域规约（编码改动前必读）。每节末附**可验证命令**——代理执行这些命令即可自查合规，不靠自觉。

---

## 1. 基本要求

### 1.1 仓库结构（新增文件必须落位）

```
backend/
├── app/
│   ├── main.py              # FastAPI 入口（唯一）
│   ├── api/                 # 路由层：只做参数校验 + 调用 service
│   ├── core/                # 配置/安全/脱敏/常量
│   ├── models/              # SQLAlchemy 模型（与 DDL 严格一致）
│   ├── schemas/             # Pydantic（请求/响应契约）
│   ├── services/            # 业务逻辑（解析/检索/导出/生成编排）
│   ├── agents/              # LangGraph 图与节点
│   └── prompts/             # YAML 提示词模板（外置，可调优）
├── worker/                  # Arq 任务（parse/index/generate/export）
├── tests/                   # 单测+接口测试（镜像 app/ 结构）
├── e2e/                     # Playwright 全链路测试
└── alembic/                 # 迁移脚本
frontend/
├── src/views/               # login/projects/kb/parse/generate/review
└── src/api/                 # REST + WS 客户端
deploy/
└── docker-compose.yml
.github/workflows/ci.yml     # CI 门禁（见 AGENTS.md 铁律 2/3）
docs/                        # 方案书 / SDD / MVP / agents 分域规约 / decisions
```

### 1.2 常用命令（完整、统一；失败先检查对应文件是否存在）

```bash
# 本地一键自检（CI 的本地等价物）—— 见 make check 脚本（Makefile 或 scripts/check.sh）
make check                     # lint + format + mypy + test + coverage 全部跑

# 后端
cd backend
python -m pip install -r requirements.txt        # 运行依赖
python -m pip install -r requirements-dev.txt    # 开发依赖（pytest/ruff/mypy/pip-audit）
uvicorn app.main:app --reload --port 8000        # 本地起服
pytest -x -q                                     # 全部单测
alembic upgrade head                             # 迁移到最新
ruff check . && ruff format --check .            # lint + 格式
mypy app                                         # 类型检查

# 前端
cd frontend
pnpm install && pnpm dev
pnpm lint && pnpm build

# E2E（需 docker compose 全栈起）
cd e2e && npx playwright test

# 全栈
docker compose -f deploy/docker-compose.yml up -d

# 安全（见 security.md）
make security-check            # gitleaks + pip-audit + pnpm audit
```

> 前置文件约定：`requirements.txt` / `requirements-dev.txt` / `pnpm-lock.yaml` 必须与依赖变更同步更新（见 §3.2 依赖变更规约）；`Makefile` 或 `scripts/check.sh` 由仓库初始化时落地，内容与 CI 一致。

### 1.3 环境与配置

- 配置走 `app/core/config.py`（Pydantic Settings），环境变量前缀 `BID_`；
- **禁止**硬编码密钥/模型名/URL；`.env` 不入库（提交 `.env.example`）；
- LLM 模型路由在 `config/llm.yaml`（经 LiteLLM），改动需评审。

## 2. 项目约定

### 2.1 命名规范

| 对象 | 规范 | 示例 |
|---|---|---|
| Python 模块 | snake_case | `services/parse_service.py` |
| Python 类 | PascalCase | `BidParseService` |
| TS 组件 | PascalCase + 目录同名 | `views/GenerateWorkbench.vue` |
| API 路由 | 小写连字符复数 | `/api/v1/projects/{pid}/score-points` |
| 数据库表 | snake_case 复数 | `score_points` |
| 数据库列 | snake_case | `clause_no` |
| 对外 JSON | camelCase | `clauseNo`, `riskLevel` |
| LangGraph 节点 | 小写动词 | `parse`, `rewrite` |
| Git 分支 | `feat/` `fix/` `chore/` 前缀 | `feat/parse-score-points` |

### 2.2 Git 工作流

- `main` 受保护，禁止直接推送；开发走 `feat/xxx` → PR；
- 提交信息：Conventional Commits（`feat:` `fix:` `test:` `docs:` `refactor:`）+ 中文正文简述改动与原因；
- PR 要求：标题即摘要；关联需求/文档；**CI 全绿 + 覆盖率达标 + 安全自检通过**才可合并；
- 禁止 force push 到共享分支；>5MB 文件禁止入库（走 MinIO）。

### 2.3 代码风格

- Python：ruff（lint+format，行宽 100）；类型注解全覆盖（mypy 门禁）；
- TypeScript：ESLint + Prettier；组件 props 用 `withDefaults` 定义类型；
- 公共函数/方法必须有 docstring（参数+返回）；禁止魔法数字。

### 2.4 文档约定

- 注释解释"为什么"，不解释"是什么"；
- 设计变更必须同步 SDD 与本文档；API 变更同步 SDD §5；
- 提示词改动必须跑 `tests/fixtures/prompt_cases.json` 回归，另可跑 `make eval` 一键离线评测（mock 模式跑通回归样本：coverage/retrieval 为真实指标，extraction 在 mock 下自动跳过，需配置 API Key 才有准召率意义；`--check` 用于门禁，skipped 不计失败）。

## 3. 开发规约

### 3.1 代码设计原则（SOLID · 松耦合高内聚）

#### 3.1.1 松耦合 · 高内聚（首要原则）

- **高内聚**：一个模块只承担一个职责——`parse_service` 只解析、`rag_service` 只检索、`export_service` 只导出；服务职责超出"一个动词"或超过约 400 行必须拆分；
- **松耦合**：模块间通过 service 层接口通信；禁止共享全局可变状态、禁止隐式依赖（模块级缓存、全局单例）；LangGraph 节点只依赖 `State` 与已注册工具（见 §3.5）；
- **控制 import 面**：单文件 import 数 > 20 视为耦合过高，需评审拆分。

#### 3.1.2 SOLID 原则（本项目落地映射）

| 原则 | 落地要求 |
|---|---|
| S 单一职责 | service 一个公开职责；LangGraph 节点一个动作 |
| O 开闭原则 | 新模型 → `config/llm.yaml`（网关扩展）；新解析器 → 注册表；不修改核心代码 |
| L 里氏替换 | 业务代码只经 LiteLLM 网关调模型，禁止直连具体厂商 SDK |
| I 接口隔离 | service 只暴露最少方法；不把内部细节（分块函数等）暴露给调用方 |
| D 依赖倒置 | 存储/外部服务经抽象（repository / client 协议）注入，便于切换与 mock |

#### 3.1.3 其他设计原则

- **DRY**：公共逻辑（脱敏 / 审计 / 错误包装 / 分页）收敛到 `app/core/`；同一逻辑出现 ≥ 3 处必须抽取；
- **YAGNI**：MVP 不实现二期占位（如 Reranker 接口）；不为"可能用到"提前抽象；
- **KISS**：优先简单方案（pgvector 单库而非 Milvus 集群）；复杂方案必须在 PR 中说明理由；
- **组合优于继承**：行为复用用依赖注入与组合，禁止继承层级 > 2 层。

**验证命令（CI 可执行）**：
```bash
# 耦合检查：服务文件 import 数（>20 需评审拆分）
for f in backend/app/services/*.py; do
  n=$(awk '/^(from|import) /{c++} END{print c+0}' "$f")
  [ "$n" -gt 20 ] && echo "COUPLING WARN: $f ($n imports)"
done
# 禁止业务代码直连具体模型 SDK（应经 LiteLLM 网关）
grep -rn "import openai\|import dashscope\|import zhipuai\|import qianfan" backend/app/ || echo "OK: 无直连 SDK"
# 禁止可变默认参数（def f(x=[] / {}））
grep -rnE "def .*=\[\]|def .*=\{\}" backend/app/ || echo "OK: 无可变默认参数"
# 禁止吞异常（与 §3.6 一致）
grep -rn "except Exception: *pass\|except: *pass" backend/app/ || echo "OK"
```

### 3.2 架构约束（分层铁律）

依赖方向：`api → services → agents / models / external(LLM, MinIO, pgvector)`

- 路由层禁止业务逻辑；services 禁止操作 HTTP 对象；models 禁止业务方法；
- 所有外部调用（LLM/MinIO/检索）必须经 services 封装（可 mock、可降级）；
- 新增第三方依赖：技术评审 → 更新 requirements*/lock → 更新 AGENTS.md 技术栈表。

**验证命令（CI 也执行）**：
```bash
# api 层不得直连 models / 数据库 / LLM 客户端
grep -rn "from app.models import\|from sqlalchemy\|from litellm\|import boto3" backend/app/api/ || echo "OK: 无跨层依赖"
# services 层不得 import api 层
grep -rn "from app.api import" backend/app/services/ || echo "OK: 无反向依赖"
```

### 3.3 数据库变更流程（Alembic）

1. 改 `app/models/` → `alembic revision --autogenerate -m "desc"`；
2. **人工审查**迁移脚本（autogenerate 可能漏索引/类型），确认后 upgrade；
3. 破坏性变更必须写数据回填脚本，禁止静默丢数据；
4. 业务表必须含 `project_id`；新表过评审；
5. 查询路径必须有索引，禁止全表扫描上线。

**验证命令**：
```bash
# 新表是否都带 project_id（业务表）
grep -rn "project_id" backend/alembic/versions/ | tail -5
# 未提交迁移但改了 model 的检查
alembic check || echo "存在未生成的迁移，先 revision"
```

### 3.4 API 设计规约

- 前缀 `/api/v1`；统一响应 `{"code":0,"data":...}`，错误 `4xxx` 业务 / `5xxx` 系统；
- 列表接口必须分页（`?page&page_size` → `{"items":[],"total":n}`）；
- 所有项目级接口校验 `project_id` 归属（越权 403）；JWT 必带；
- 长任务返回 `task_id`，进度走 `/tasks/{tid}` 或 WebSocket，禁止同步阻塞；
- 新端点必须同步 SDD §5 接口清单 + 接口测试。

**验证命令**：`grep -rn "add_api_route\|@router\." backend/app/api/ | wc -l`（新端点必须能在 SDD §5 找到对应行）。

### 3.5 LangGraph 编排规约

- 节点职责单一；状态字段先定义 TypedDict，节点只改自己负责的键；
- 每个 `write` 后必须接 `validate`；校验失败重试 ≤ 2 次，禁止无限循环；
- HITL：审阅节点必须 `interrupt()` 等待人工，禁止跳过；恢复用 `Command(resume=...)`；
- Checkpointer 用 PostgresSaver，`thread_id = project_id`；
- 新增节点必须同步 SDD §6 图定义 + 更新图；
- 提示词模板外置 YAML，节点内不内联大段 prompt。

**验证命令**：
```bash
grep -n "interrupt(" backend/app/agents/graph.py        # 审阅节点必须有 interrupt
grep -n "add_node" backend/app/agents/graph.py | wc -l  # 节点数与 SDD §6 一致
```

### 3.6 错误处理规约

- 业务异常：自定义 `BizError(code, message)`，api 层统一捕获转 JSON；
- 外部依赖调用必须 try/except + 日志 + 明确降级路径（降级矩阵见 SDD §8，实现必须一致）；
- 任务失败保留已生成章节，禁止整体回滚丢失成果。

**验证命令**：
```bash
# 禁止吞异常
grep -rn "except Exception: *pass\|except: *pass" backend/app/ || echo "OK"
```

### 3.7 数据与脱敏规约

- 外发 LLM 的文本必须先经 `app/core/redact.py` 脱敏，且有单测覆盖；
- 上传文件白名单（pdf/docx/jpg/png）、≤50MB、MIME 校验；
- 日志禁止输出密码/Token/文件全文；PII 打码。

**验证命令**：
```bash
grep -rn "redact\|mask" backend/app/services/ | head -10   # 外发路径有脱敏调用
```

## 4. 资源引用

| 文档 | 路径 | 权威性 |
|---|---|---|
| 技术方案书 | `docs/方案书.md` | 需求依据 |
| SDD | `docs/SDD.md`（§4 DDL / §5 接口 / §6 图） | **唯一权威** |
| MVP 范围 | `docs/MVP.md` | 范围判断 |
| 分域规约 | `docs/agents/*.md` | 本文档 |

关键文件速查：`backend/app/agents/graph.py`（图定义）、`backend/app/services/rag_service.py`（检索）、`backend/app/prompts/*.yaml`（提示词）、`frontend/src/views/review/`（审阅页）、`deploy/docker-compose.yml`（全栈）。
