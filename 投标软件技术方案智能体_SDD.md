# 投标软件技术方案智能体 · 软件设计文档（SDD）

| 项目名称 | 投标软件技术方案智能体（Agent 应用） |
|---|---|
| 文档版本 | V1.0（MVP 版） |
| 编制日期 | 2026-08-15 |
| 依据方案 | 《投标软件技术方案智能体·技术方案书 V1.0》 |
| 设计范围 | MVP（P0 核心闭环 + P1 体验必需） |

---

## 一、文档概述

### 1.1 目的

本文档基于已确认的 MVP 范围，对投标软件技术方案智能体进行软件设计，作为开发、测试、评审与验收的依据，明确各模块的职责、数据结构、接口契约与关键技术实现方案。

### 1.2 设计范围（MVP 边界）

**范围内**：
- 简单账号登录 + 项目级隔离（不做 RBAC）；
- 真实资料批量入库与向量检索（RAG 底座，不做重排/评测集）；
- 招标文件解析（PDF/Word → 评分点/★条款/资格要求结构化提取）；
- 评分点对标分析；
- 方案骨架生成与章节内容生成（含校验）；
- 章节级人工审阅反馈与局部重写（不做行内批注/diff）；
- 流式输出；Word 文档导出（固定模板）。

**范围外（二期）**：版本管理与 diff、RBAC 角色权限、Reranker 精排、多模型路由降级、OCR 扫描件、商务/报价标生成、私有化部署。

### 1.3 读者

后端/Agent 工程师、前端工程师、AI 算法工程师、测试工程师、项目经理。

---

## 二、系统架构设计

### 2.1 架构总览（MVP 简化版）

```
┌────────────────────────────────────────────────────────┐
│ 浏览器（Vue3 + Ant Design Vue）                          │
│  登录 / 项目管理 / 资料库 / 解析确认 / 生成工作台 / 审阅  │
├────────────────────────────────────────────────────────┤
│ API 网关（FastAPI） · WebSocket（流式输出）               │
├────────────────────────────────────────────────────────┤
│ Agent 编排引擎（LangGraph）                              │
│  解析 → 对标 → 骨架 → 章节生成(HITL) → 整合 → 导出       │
├───────────────┬──────────────────┬──────────────────────┤
│ 解析服务       │ RAG 服务          │ 导出服务             │
│ PDF/Word抽取   │ 分块/向量化/检索   │ python-docx 模板渲染 │
│ 评分点结构化   │ pgvector 检索     │                      │
├───────────────┴──────────────────┴──────────────────────┤
│ PostgreSQL（业务+向量）· MinIO（文件）· Redis（队列/流）  │
├────────────────────────────────────────────────────────┤
│ LLM 网关（LiteLLM）：DeepSeek-V3（主）· Qwen（备）       │
└────────────────────────────────────────────────────────┘
```

### 2.2 技术栈（MVP 锁定）

| 层级 | 选型 | 说明 |
|---|---|---|
| 前端 | Vue 3 + TypeScript + Ant Design Vue + Vite | 工作台 UI、docx-preview 预览 |
| 后端 | Python 3.12 + FastAPI + SQLAlchemy 2.0 + Alembic | REST API、异步任务 |
| Agent 编排 | LangGraph（Checkpointer = Postgres） | 状态机 + HITL 中断恢复 |
| RAG | LlamaIndex 或自研 loader + pgvector | MVP 用 pgvector 单库，避免额外组件 |
| 向量库 | pgvector（PostgreSQL 扩展） | 数据量 < 10 万 chunk，够用 |
| 数据库 | PostgreSQL 16 | 业务 + 向量一体 |
| 对象存储 | MinIO（Docker 单机） | 原始文件与导出文档 |
| 队列/缓存 | Redis 7 + Arq | 长任务队列、会话缓存 |
| 文档解析 | Unstructured + PyMuPDF + python-docx | 文本/表格抽取 |
| 文档导出 | python-docx + Jinja2 | 固定标书模板渲染 |
| LLM 网关 | LiteLLM | DeepSeek-V3 主用、Qwen-Plus 备用 |
| Embedding | bge-m3（本地/API） | 中文语义检索 |
| 部署 | Docker Compose（单机） | 网关 + 前后端 + 中间件 |

**MVP 架构决策**：不引入 Milvus、Kafka、K8s；全部组件 Docker Compose 单机部署，降低运维成本；预留迁移路径（pgvector → Milvus、单机 → K8s）。

### 2.3 部署拓扑

```
docker-compose.yml
├── web（nginx 静态 + 反代）
├── api（FastAPI，uvicorn 多 worker）
├── worker（Arq 消费长任务：解析/生成/导出）
├── postgres（含 pgvector 扩展）
├── redis
└── minio
```

---

## 三、功能模块详细设计

### 3.1 用户认证与项目管理模块

**职责**：账号登录（用户名/密码 + JWT）、项目 CRUD、项目级数据隔离。

**设计要点**：
- 密码哈希：bcrypt；JWT（access 2h / refresh 7d）；
- 项目表含 `owner_id`，所有业务数据（文档/方案/批注）携带 `project_id`，查询强制过滤；
- 不做角色表，登录用户即项目成员（创建者为 owner，可添加协作者 email 列表）；
- 中间件统一校验 JWT 与项目权限。

**核心流程**：注册/登录 → 创建项目 → 邀请协作者（MVP 仅按 email 加入）→ 进入项目工作台。

### 3.2 资料库管理模块（RAG 底座）

**职责**：真实资料（产品手册/历史方案/资质证书）批量上传、解析、分块、向量化、检索。

**入库流水线**：

```
上传(MinIO) → 解析(Unstructured: pdf/docx) → 清洗(去页眉页脚)
  → 分块(语义段落 500~800 字，表格独立成块)
  → 向量化(bge-m3) → 写入 kb_chunks(pgvector) + 元数据
```

**元数据 Schema**：
```json
{
  "doc_id": "uuid", "doc_type": "product_manual|case_study|certificate|patent",
  "title": "XX平台技术白皮书", "product_line": "数据中台",
  "industry": "政务|金融|能源", "cert_no": "ISO27001-...",
  "upload_by": "user_id", "upload_at": "ISO8601",
  "chunks": [{"chunk_id": "uuid", "content": "...", "page_no": 12, "embedding": "[...]"}]
}
```

**检索接口**：`query(q, filters)` → Embedding 相似度（cosine）Top-K=20 → 按 project_id 可见范围过滤 → 返回 `[{chunk, doc_meta, score}]`。MVP 不做 RRF/重排，仅向量检索 + 元数据过滤；BM25 关键词检索作为兜底开关。

**异步处理**：上传走 Arq 任务队列，前端轮询解析/索引状态（progress 字段）。

### 3.3 招标文件解析模块

**职责**：上传招标文件 → 抽取文本与结构 → LLM 提取评分点/资格/技术需求 → 人工确认。

**处理管线**：
1. 文件上传（.pdf/.doc/.docx → MinIO，登记 documents 表）；
2. 文本抽取：Unstructured 抽取正文与表格，保留章节层级（标题字号/编号）；
3. 结构切分：招标公告/投标人须知/评标办法/技术需求/合同条款；
4. LLM 结构化提取（tool calling + JSON Schema）：
   - score_points：`[{clause_no, item, score, criteria, is_star}]`
   - qualifications：`[{category, requirement, evidence}]`
   - tech_requirements：`[{seq, description, category, is_mandatory}]`
5. 人工确认页：解析结果表格化展示，可增删改；确认后落库、状态置 `parsed`。

**校验**：提取结果二次回读原文核对（LLM 自检 + 关键字段（★条款数）人工确认）；非法 JSON 自动重试 ≤2 次。

**表**：`documents`（status: uploaded→parsing→parsed→confirmed）、`score_points`、`tech_requirements`。

### 3.4 评分对标分析模块

**职责**：基于评分点生成对标报告，指导撰写优先级。

**对标表字段**：`clause_no / item / score / criteria / strategy / referenced_material / risk_level(high|mid|low)`。

**风险分级算法**：`risk = f(score, coverage)` —— 分值高且资料库无对应素材 → high，提示售前补资料；输出按 `score × (1 - coverage)` 降序，供前端排序展示。

**输出物**：Web 内联对标表（可编辑 strategy 字段）+ 导出附表（随 Word 导出）。

### 3.5 方案生成引擎（Agent 编排核心）

**职责**：骨架生成 → 逐章节（检索→撰写→校验）→ 全文整合 → 人工审阅 → 导出。

**LangGraph 状态图（MVP）**：

```
节点: parse → skeleton → (for each section: retrieve → write → validate)
      → integrate → review(HITL) → rewrite(局部) → export
边:   validate fail → write（重试 ≤2）
      review 批注非空 → rewrite 对应节点 → review
      review 通过 → integrate/export
```

**状态（State）**：
```python
class BidState(TypedDict):
    project_id: str
    doc_id: str
    score_points: list[ScorePoint]
    skeleton: list[SectionPlan]          # {id, title, score_point_ids, word_target}
    sections: dict[str, str]             # section_id -> markdown 正文
    summaries: dict[str, str]            # section_id -> 摘要（供后续章节引用）
    review_feedback: dict[str, list[Review]]
    glossary: list[str]                  # 术语表
    output_docx_path: str | None
```

**上下文管理**：全局只保留 skeleton + 每章摘要；每章独立窗口生成，注入「前文摘要 + 本章评分要求 + RAG 检索素材 + 术语表」。

**HITL 设计**：每章 `write` 完成后节点 `interrupt()`，等待用户「通过/改稿/重写」；Checkpointer（Postgres）持久化图状态，支持任务中断后恢复。

**校验节点**：必答要点清单（该章对应 score_points 是否全部应答）、字数下限、★参数不低于招标要求（LLM 比对 + 规则检查）；失败自动重写 ≤2 次。

### 3.6 人工审阅与重写模块

**职责**：章节级审阅，反馈后局部重写，形成新版本。

**MVP 交互**：
- 审阅页：左侧章节树 + 右侧 Markdown 渲染（预览）；
- 每章操作：通过 / 编辑（直接改正文）/ 反馈重写（输入修改意见）；
- 编辑与反馈均写入 `reviews` 表 → 触发 `rewrite` 节点仅重写该章（携带原文 + 反馈 + 检索素材）；
- 版本：MVP 不做版本表，重写即覆盖 + `updated_at` 留痕；批注历史保留在 reviews 表（可追溯）。

### 3.7 文档导出模块

**职责**：方案 Markdown → 标书模板 .docx。

**渲染流程**：Markdown → 结构树（标题层级/表格/列表）→ python-docx 按模板样式写入 → 目录域（打开自动更新）→ 页码/分页。

**MVP 模板**：单套公司标准模板（封面 + 目录 + 正文样式 + 附表：评分对照表、资质索引表）。

### 3.8 流式输出模块

**职责**：章节生成内容实时推送前端。

**设计**：FastAPI WebSocket（`/ws/{project_id}`）；节点生成时经 Redis pubsub 发布事件（`bid:events:{project_id}`），WebSocket 端点订阅并转发前端；前端流式渲染；断线重连后拉取已生成缓存（sections 已落库）。

**握手鉴权**（实现于 `app/api/websocket.py`）：连接 URL 携带 query 参数 `token`（JWT access token）；服务端在握手阶段校验 token 有效性与项目成员资格，失败即关闭连接（close code `4001` 未认证 / `4003` 非成员），不发送任何业务消息；refresh token 一律拒绝。

---

## 四、数据库设计（PostgreSQL 16 + pgvector）

### 4.1 DDL 草案（核心表）

```sql
-- 用户
CREATE TABLE users (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email       TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  display_name TEXT NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 项目
CREATE TABLE projects (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name        TEXT NOT NULL,
  tender_no   TEXT,
  industry    TEXT,
  status      TEXT NOT NULL DEFAULT 'active',  -- active|archived
  deadline    TIMESTAMPTZ,
  owner_id    UUID NOT NULL REFERENCES users(id),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 项目成员（MVP：owner + 协作者，无角色）
CREATE TABLE project_members (
  project_id  UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id     UUID NOT NULL REFERENCES users(id),
  PRIMARY KEY (project_id, user_id)
);

-- 文档（招标文件/资料/导出物）
CREATE TABLE documents (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id  UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  doc_type    TEXT NOT NULL,        -- tender_file|kb_material|export
  title       TEXT NOT NULL,
  storage_key TEXT NOT NULL,        -- MinIO key
  status      TEXT NOT NULL DEFAULT 'uploaded', -- uploaded|parsing|parsed|confirmed|indexed|failed
  meta        JSONB NOT NULL DEFAULT '{}',
  created_by  UUID REFERENCES users(id),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 评分点
CREATE TABLE score_points (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id  UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  doc_id      UUID NOT NULL REFERENCES documents(id),
  clause_no   TEXT NOT NULL,
  item        TEXT NOT NULL,
  score       NUMERIC,
  criteria    TEXT,
  is_star     BOOLEAN NOT NULL DEFAULT false,
  strategy    TEXT,                 -- 人工可编辑
  risk_level  TEXT,                 -- high|mid|low
  confirmed   BOOLEAN NOT NULL DEFAULT false
);

-- 技术需求清单
CREATE TABLE tech_requirements (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id  UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  doc_id      UUID NOT NULL REFERENCES documents(id),
  seq         INT NOT NULL,
  description TEXT NOT NULL,
  category    TEXT,
  is_mandatory BOOLEAN NOT NULL DEFAULT false
);

-- 方案骨架
CREATE TABLE proposal_skeletons (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id  UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  tree        JSONB NOT NULL,       -- 章节树 [{id,title,score_point_ids,word_target}]
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (project_id)
);

-- 方案章节
CREATE TABLE proposal_sections (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id  UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  section_id  TEXT NOT NULL,        -- 骨架中的章节 id
  title       TEXT NOT NULL,
  content_md  TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'draft', -- draft|generating|review|approved
  citations   JSONB NOT NULL DEFAULT '[]',  -- [{chunk_id, doc_title, page_no}]
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (project_id, section_id)
);

-- 审阅反馈
CREATE TABLE reviews (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id  UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  section_id  TEXT NOT NULL,
  action      TEXT NOT NULL,        -- approve|edit|rewrite
  content     TEXT,                 -- 修改后正文（edit）或修改意见（rewrite）
  created_by  UUID REFERENCES users(id),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 资料库分块（含向量）
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE kb_chunks (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  doc_id      UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  chunk_index INT NOT NULL,
  content     TEXT NOT NULL,
  page_no     INT,
  embedding   vector(1024),         -- bge-m3 输出维度
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON kb_chunks USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX ON kb_chunks (doc_id);

-- 审计日志（追加式，无软删；迁移 0004_audit_logs）
CREATE TABLE audit_logs (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID REFERENCES users(id),
  action      TEXT NOT NULL,          -- 命名规范：域.动作，如 auth.login / document.upload
  project_id  UUID REFERENCES projects(id) ON DELETE SET NULL,
  target_type TEXT,
  target_id   UUID,
  detail      JSONB,                  -- 敏感字段（password/token/secret 等）写入前递归剔除
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON audit_logs (created_at);
CREATE INDEX ON audit_logs (project_id);
```

### 4.2 数据一致性要点

- 所有业务表以 `project_id` 隔离，API 层强制过滤；
- `documents.doc_type='kb_material'` 与 `kb_chunks` 联动：入库失败回滚状态；
- 生成任务以 `documents`（导出物）或任务表记录进度；MVP 不建独立 task 表，用 Redis 任务键 + documents.status 表达。

---

## 五、接口设计

### 5.1 REST API 概览（前缀 /api/v1）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | /auth/register, /auth/login | 注册、登录（JWT） |
| POST | /auth/refresh | refresh token 换新 access token（type 校验，refresh 专用） |
| GET | /projects, POST /projects | 项目列表、创建 |
| POST | /projects/{pid}/members | 添加协作者 |
| POST | /projects/{pid}/documents | 上传文件（tender/kb） |
| GET | /projects/{pid}/documents | 文档列表与状态 |
| POST | /projects/{pid}/documents/{did}/parse | 触发招标解析 |
| GET | /projects/{pid}/score-points | 评分点列表（可 PUT 单条确认/改 strategy） |
| GET | /projects/{pid}/benchmark | 评分对标报告 |
| POST | /projects/{pid}/generate | 触发方案生成（返回 task_id） |
| POST | /projects/{pid}/workflow/start | 启动方案生成工作流（API 进程后台任务推进，遇 HITL interrupt 停下；在途重复启动被拒 4009） |
| GET | /projects/{pid}/workflow/status | 工作流状态（phase/progress/interrupt/score_points/outline/chapters/error） |
| POST | /projects/{pid}/workflow/confirm-score-points | 确认评分点，resume 工作流进入大纲阶段（前置校验 interrupt 类型） |
| POST | /projects/{pid}/workflow/confirm-outline | 确认大纲（可携带修改后大纲先回写 state），resume 进入章节生成 |
| POST | /projects/{pid}/workflow/confirm-review | 审阅确认：approved → 导出；feedback → 章节重写后复审 |
| POST | /projects/{pid}/workflow/rewrite-chapter | 按审阅意见重写指定章节（query 参数 chapter_no、comment） |
| GET | /projects/{pid}/workflow/export | 导出 Word（返回导出状态与存储 key） |
| GET | /projects/{pid}/skeleton | 方案骨架 |
| GET | /projects/{pid}/sections | 章节列表（含状态/内容） |
| PUT | /projects/{pid}/sections/{sid} | 章节编辑（人工直接改） |
| POST | /projects/{pid}/sections/{sid}/review | 审阅动作（approve/rewrite+意见） |
| POST | /projects/{pid}/export | 导出 Word（返回下载 URL） |
| GET | /tasks/{tid} | 任务进度轮询 |

### 5.2 WebSocket

- `/ws/{project_id}?token=<JWT access token>`：握手阶段鉴权（token 无效 close `4001` / 非项目成员 close `4003`，refresh token 拒绝）；连接建立后转发节点经 Redis 频道 `bid:events:{project_id}` 发布的工作流进度与章节事件，并支持客户端 `ping/pong` 心跳与 `get_status`（读取 checkpointer 实时状态）。

### 5.3 统一响应约定

```
成功: {"code": 0, "data": ...}
失败: {"code": 4001, "message": "..."}   # 4xxx 业务错误，5xxx 系统错误
分页: ?page=1&page_size=20 → {"items": [], "total": n}
```

---

## 六、Agent 编排设计（LangGraph）

### 6.1 图定义

```python
graph = StateGraph(BidState)
graph.add_node("parse", parse_node)            # 解析评分点（已有则跳过）
graph.add_node("skeleton", skeleton_node)      # 生成章节树
graph.add_node("retrieve", retrieve_node)      # RAG 检索当前章节素材
graph.add_node("write", write_node)            # 撰写章节
graph.add_node("validate", validate_node)      # 校验章节
graph.add_node("integrate", integrate_node)    # 术语/编号/目录整合
graph.add_node("review", review_node)          # HITL：interrupt() 等人工
graph.add_node("rewrite", rewrite_node)        # 按反馈局部重写
graph.add_node("export", export_node)          # 导出 Word

graph.add_edge("parse", "skeleton")
graph.add_edge("skeleton", "retrieve")
graph.add_conditional_edges("write", validate_route, {"ok": "integrate", "retry": "write", "next": "retrieve"})
graph.add_edge("integrate", "review")
graph.add_conditional_edges("review", review_route, {"approved": "export", "feedback": "rewrite"})
graph.add_edge("rewrite", "integrate")
graph.add_edge("export", END)

# 章节循环：skeleton 后对每个 section 执行 retrieve→write→validate
```

### 6.2 HITL 与中断恢复

- `review_node` 内调用 `interrupt({section_id, content_md, score_points})`；
- 用户通过 / 编辑 / 重写后 `Command(resume=...)` 恢复执行（resume 前校验 pending interrupt 类型匹配，不匹配拒绝）；
- Checkpointer：`PostgresSaver` 持久化，`thread_id = project_id`，支持任务中断后从断点续跑；
- 长任务：工作流由 API 进程的 asyncio 后台任务推进（不经 Arq worker），Checkpointer 采用 AsyncPostgresSaver + 独立 psycopg 连接池（不与业务 SQLAlchemy 会话混用），由 app lifespan 初始化/释放；Arq worker 仅用于招标文件解析、资料入库等异步任务。前端通过 WebSocket 接收进度与 interrupt 通知。

### 6.3 工具注册

| 工具 | 用途 | 授权 |
|---|---|---|
| kb_search | 资料库检索（embedding 相似度） | 自动 |
| get_score_points | 读取当前项目评分点 | 自动 |
| list_sections | 读取已生成章节 | 自动 |
| update_glossary | 更新术语表 | 自动 |
| web_search | 行业公开资料检索 | 二期（需人工授权） |

### 6.4 提示词体系（MVP 五件套）

| 提示词 | 输入 | 输出 | 关键约束 |
|---|---|---|---|
| 招标解析器 | 评标办法原文 | JSON（评分点/资格/需求） | JSON Schema、禁止臆测分值 |
| 骨架规划器 | 评分点+技术需求 | 章节树 JSON | 评分点全覆盖映射 |
| 章节撰写器 | 章节计划+检索素材+前文摘要 | Markdown 正文 | 只用检索素材、参数不低于★要求 |
| 校验器 | 正文+评分要求 | pass/fail+issues | 必答要点/字数/参数检查 |
| 批注重写器 | 原文+反馈+素材 | 重写后 Markdown | 仅改反馈涉及内容 |

---

## 七、RAG 检索设计

### 7.1 分块策略（MVP）

- 语义段落分块：500~800 字/块，标题作为块前缀（保留上下文）；
- 产品参数表单独成块（保留表格结构，转文本行）；
- 每块携带元数据：doc_id、doc_type、title、product_line、industry、page_no。

### 7.2 检索链路

```
用户查询（章节主题 + 评分点描述）
  → bge-m3 Embedding（query）
  → pgvector cosine 检索 Top-K=20（限定该用户可见 doc 集合）
  → 去重 + 按 doc_type 加权（case_study 优先）
  → 返回 Top-8 素材给撰写节点
```

### 7.3 质量兜底

- 检索为空 → 提示"资料库无相关内容"，撰写节点降级为基于通用知识撰写并标记"待人工补充"；
- 引用溯源：写入 `proposal_sections.citations`，导出时标注 `【来源：XX P12】`；
- MVP 不引入 Reranker/评测集（P2），用人工确认页兜底。

---

## 八、错误处理与降级

| 场景 | 处理 |
|---|---|
| 招标文件解析失败（格式/扫描件） | 状态置 failed + 错误原因展示；支持重新上传；扫描件提示暂不支持 |
| LLM 超时/限流 | 重试 2 次（指数退避）；仍失败 → 任务失败并通知，保留已生成章节 |
| 非法 JSON 输出 | 自动重试 ≤2 次，仍失败 → 人工修正入口 |
| 检索服务不可用 | 降级关键词搜索（ILIKE）；仍失败 → 无素材生成 + 标记 |
| 生成中断 | Checkpointer 断点恢复；未完成章节标记 generating，可续跑 |
| 上传文件损坏 | 校验 MIME/大小（≤50MB），解析失败提示重新上传 |

---

## 九、安全设计

- JWT 认证 + 项目级权限中间件（非成员请求一律 403）；WebSocket 同样强制握手鉴权（query token + 成员校验，close code 4001/4003）；
- 密码 bcrypt 哈希；HTTPS 全链路（网关 TLS）；
- 上传文件白名单（pdf/docx/jpg/png）、大小限制、病毒扫描（MVP 可选 ClamAV）；
- LLM 外发内容脱敏（铁律，默认开启不可关闭）：`app/core/redact.py` 的 `redact()` 正则替换手机号/身份证/银行卡/邮箱，在 parse/chapter/review 三个拼接点前置脱敏，并在 `llm_service` 出口兜底；
- 审计：统一封装 `app/core/audit.py::record()` 写入追加式 `audit_logs` 表，已在登录/token 刷新/上传/工作流启动与导出/成员变更埋点；业务表继续记录 created_by 与时间。

---

## 十、测试与验收

### 10.1 测试分层

| 层级 | 范围 | 工具 |
|---|---|---|
| 单元测试 | 分块、解析校验、风险分级、导出渲染 | pytest |
| 接口测试 | REST/WS 契约、权限隔离 | pytest + httpx |
| Agent 集成 | LangGraph 全链路（含 interrupt 恢复） | pytest + 测试项目 fixture |
| 端到端 | 上传→出稿→审阅→导出 | Playwright（可选） |
| 人工验收 | 1-2 个真实项目试跑 | 业务人员 |

### 10.2 验收标准（对齐 MVP 目标）

| 指标 | 目标 |
|---|---|
| 评分点提取准召率 | ≥ 85% |
| 方案评分点覆盖 | ≥ 90% |
| 单项目出稿时间 | ≤ 4 小时 |
| 输出 Word 可编辑 | 目录/页码/样式规范 |
| 检索命中 | 章节相关素材 Top-8 有效 |
| 中断恢复 | 断点续跑成功 |

### 10.3 冒烟用例（开发自测）

1. 注册 → 登录 → 创建项目；
2. 上传招标文件 → 解析 → 人工确认评分点；
3. 上传 3 份产品手册 → 检索命中；
4. 触发生成 → 逐章流式输出 → 审阅一章反馈重写；
5. 导出 Word → 打开检查格式。

---

## 十一、附录

### 11.1 目录结构（建议）

```
backend/
├── app/
│   ├── main.py                 # FastAPI 入口
│   ├── api/                    # 路由（auth/projects/docs/generate/export）
│   ├── core/                   # 配置、安全、脱敏
│   ├── models/                 # SQLAlchemy 模型
│   ├── schemas/                # Pydantic Schema
│   ├── services/               # 解析/检索/导出/生成服务
│   ├── agents/                 # LangGraph 图定义与节点
│   └── prompts/                # YAML 提示词模板
├── worker/                     # Arq 任务（parse/index/generate/export）
├── tests/
└── alembic/                    # 迁移
frontend/
├── src/views/                  # login/projects/kb/parse/generate/review
└── src/api/                    # REST + WS 客户端
deploy/
└── docker-compose.yml
```

### 11.2 二期预留点

- `kb_chunks.embedding` 维度与 pgvector 索引 → 迁移 Milvus；
- 模型层通过 LiteLLM 路由 → 扩展多模型；
- reviews 表已有完整记录 → 扩展版本表与 diff；
- 权限模型 project_members → 扩展 roles。

### 11.3 待确认项

1. 公司标书模板样式（封面/页眉页脚/字号规范）需售前团队提供；
2. 首批入库资料清单（3 份产品手册 + 2 份历史方案）；
3. LLM 供应商账号与预算（DeepSeek 主用 + Qwen 备用）；
4. 服务器资源申请（8C16G × 2）。
