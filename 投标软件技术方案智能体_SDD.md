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

**实现约束（2026-08-16）**：文本抽取实现为 pdfplumber（PDF）/ python-docx（段落 + 表格，按文档顺序）；送 LLM 前先经 `select_parse_window` 选取窗口（预算 4 万字符）再脱敏：封面头部 + 评分细则区锚定窗口（细则关键词优先于“评标办法前附表”等汇总性锚点）+ 技术要求区锚定窗口——仅固定截前 N 字符或锚定前附表会让评分细则/技术需求落窗外，导致提取为空或“详见招标文件”类笼统描述。

**表**：`documents`（status: uploaded→parsing→parsed→confirmed）、`score_points`、`tech_requirements`。

**技术需求梳理（评分点确认后，2026-08-16）**：人工确认要响应的评分点后，`POST /requirements/generate` 经 LLM（prompts/requirements.yaml）从评分项内容（item+criteria+分值+星级）提炼可验证的技术需求并回填映射（tech_requirements.sp_id）。映射键为评分点唯一标识 `clause_no|item`（同一条款号下可能存在多个评分项，仅用 clause_no 会互相覆盖；LLM 仅写条款号且唯一时降级容错）。幂等：同项目重复梳理先删旧 sp_derived 再重建，招标原文提取的需求（source 为 NULL/tender）不受影响；seq 从存量最大值续编。重新解析（reparse）只负责评分点提取：清除旧评分点与 sp_derived 衍生需求，保留招标原文技术需求，并以 score_points_only=True 入队（worker 解析 schema 裁掉 tech_requirements，不重复提取）；前端入口唯一，位于确认页评分点卡片操作区（与批量修改策略/一键全确认并列，最右侧）。

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

**事件协议**（`event_service.py`，前后端统一）：

| 事件 | 负载 | 说明 |
|---|---|---|
| `progress` | `{phase, progress, current_chapter}` | 阶段进度（outline/generate/review） |
| `section_token` | `{chapter_no, delta}` | 三期真流式增量文本块（write_node 节流发布：累积 ≥40 字符或距上次 ≥200ms 取先到者；尾部缓冲兜底 flush，delta 拼接 == 全文） |
| `section_done` | `{chapter_no, title, content}` | 章节完成（携带全文，供断线重连/丢块兜底对齐） |
| `task_done` | `{export_storage_key}` | 全流程完成 |
| `error` | `{message}` | 异常 |

**三期真流式链路**（已实现）：`llm_service.call_llm_stream`（mock 模式将 _MOCK_TEXT 按 ~20 字切片 yield；真实模式 `acompletion(stream=True)` 逐 chunk yield delta，出口同 call_llm_text 脱敏）→ `chapter_service.generate_chapter(on_delta=...)` 逐块回调并累积全文（未传 on_delta 时保持非流式，向后兼容）→ `write_node` 经 on_delta 节流发布 `section_token`，结束后照旧落库 + `section_done`（全文）+ `progress`；前端 GenerateView 对 `section_token` 增量追加渲染（已移除假打字机定时器），`section_done` 全量覆盖对齐。

**LLM 结构化输出供应商兼容**（三期验收修复）：DeepSeek 兼容接口不支持 strict `json_schema`（报 "This response_format type is unavailable now"），`call_llm_with_schema` 内置 `_compat_response_format`：deepseek 模型自动降级为 `{"type":"json_object"}` 并将 schema 结构写入 system prompt 约束输出；其余模型（如 qwen）保持 json_schema 原样透传。

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
  role        VARCHAR(20) NOT NULL DEFAULT 'member', -- 三期：member|kb_admin|admin（迁移 0007_users_role，白名单邮箱回填 admin）
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
  project_id  UUID REFERENCES projects(id) ON DELETE CASCADE, -- 二期：可空，NULL = 全局资料（迁移 0006_documents_project_nullable）
  doc_type    TEXT NOT NULL,        -- tender_file|kb_material|export
  title       TEXT NOT NULL,
  storage_key TEXT NOT NULL,        -- MinIO key
  status      TEXT NOT NULL DEFAULT 'uploaded', -- uploaded|parsing|parsed|confirmed|indexed|failed
  meta        JSONB NOT NULL DEFAULT '{}',
  category    VARCHAR(30),          -- 三期：素材分类 product_material|history_proposal|qualification|other，NULL = 未分类（迁移 0008）
  tags        JSON NOT NULL DEFAULT '[]', -- 三期：自由标签（≤10 个、每个 ≤20 字符，schema 层校验）
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
  is_mandatory BOOLEAN NOT NULL DEFAULT false,
  -- 评分点→技术需求梳理映射（迁移 0009）
  sp_id       UUID REFERENCES score_points(id) ON DELETE SET NULL,  -- NULL=通用需求不归属具体评分点
  source      VARCHAR(20)  -- sp_derived=评分点梳理衍生 / tender=招标原文提取（NULL=存量）
);

-- 方案骨架
CREATE TABLE proposal_skeletons (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id  UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  tree        JSONB NOT NULL,       -- 章节树 [{chapter_no,title,sections,covered_clauses,word_target}]（covered_clauses=覆盖的评分点条款号数组）
  draft       JSONB,                -- 大纲二次编辑草稿 {"outline":[...], "mounted_doc_ids":[...]|null}（迁移 0010，确认大纲后清除防陈旧）
  draft_updated_at TIMESTAMPTZ,     -- 草稿最近保存时间（前端防抖 2s 自动 + 手动 + 刷新恢复）
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

-- LLM 页面配置（全局单行 upsert；密钥列存 Fernet 密文，key 优先由 BID_LLM_CRYPTO_SECRET 派生、未配置回退 jwt_secret；迁移 0005_llm_settings）
CREATE TABLE llm_settings (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  deepseek_api_key_enc  VARCHAR(512),   -- Fernet 密文；NULL = 未配置
  dashscope_api_key_enc VARCHAR(512),   -- Fernet 密文；NULL = 未配置
  embedding_api_base    VARCHAR(512),   -- NULL = 回退环境变量 BID_EMBEDDING_API_BASE
  llm_mock              BOOLEAN NOT NULL DEFAULT false,  -- 与 env 任一为 true 即 mock
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
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
| GET | /settings/llm | 读取 LLM 页面配置（全局，无项目上下文，普通登录用户可读；密钥脱敏为 sk-****+后4位，附 deepseek/dashscope_configured 标志，永不返回明文） |
| PUT | /settings/llm | 更新 LLM 页面配置（**仅管理员**，BID_ADMIN_USER_IDS 逗号分隔邮箱列表，为空拒绝写入 403；密钥字段三态契约：省略(None)=保持/""=清除/非空=更新，服务端拒收疑似脱敏串（含连续 4 星号）；embedding_api_base 必填且做 SSRF 校验（禁私网/本机段，debug 档放行 loopback）；密钥 Fernet 加密入库（优先 BID_LLM_CRYPTO_SECRET 派生）；审计 settings.llm_update 的 detail 只记变更字段名；运行时缓存于 commit 成功后失效） |
| POST | /settings/llm/test | LLM/Embedding 连通性测试（**仅管理员**；body target=llm\|embedding；15s 超时、异常全捕获，业务结果 data.ok=true/false，HTTP 恒 200） |
| POST | /kb/materials | 全局资料库上传（二期：project_id IS NULL 全局共享；登录可用；审计 kb.material_upload；入队向量化；三期：Form 可选参数 category 枚举校验、tags 逗号分隔字符串，服务端拆分校验 ≤10 个/每个 ≤20 字符） |
| GET | /kb/materials | 全局资料库列表（仅 project_id IS NULL 的 kb_material；分页 page/page_size；三期：查询参数 category/tag 精确过滤（tag 用 PG JSON 包含 `tags @> '["tag"]'`，tags 为 JSON 列需 cast 为 jsonb 后使用 @>），LEFT JOIN users 返回 uploader_name（created_by 为空时空串），列表项含 category/tags） |
| PATCH | /kb/materials/{doc_id} | 全局素材编辑（三期：**仅资料库管理员** get_current_kb_admin_id；body title/category/tags 均可选，复用上传同套枚举/标签校验；审计 kb.material_update 记录变更字段） |
| DELETE | /kb/materials/{doc_id} | 全局资料删除（三期：**仅资料库管理员** get_current_kb_admin_id（role ∈ kb_admin/admin 或白名单兼容），非管理角色 403；限 project_id IS NULL，项目级文档 4004 隔离；MinIO 文件 + 记录 + 分块 CASCADE；审计 kb.material_delete） |
| GET | /kb/materials/search | 全局资料库检索测试（q 必填，top_k∈[1,20]；仅检索全局资料 doc_ids 范围；返回 {items:[{chunk_id,doc_id,title,content,page_no,score}],total}） |
| GET | /projects, POST /projects | 项目列表、创建 |
| POST | /projects/{pid}/members | 添加协作者 |
| POST | /projects/{pid}/documents | 上传文件（tender/kb） |
| GET | /projects/{pid}/kb/search | 资料库相似度检索（RAG；query 参数 q 必填，top_k∈[1,20] 默认 5，按相似度倒序返回 {items,total}，仅项目成员可调） |
| GET | /projects/{pid}/documents | 文档列表与状态 |
| POST | /projects/{pid}/documents/{did}/reparse | 重新解析招标文件（只提取评分点，不提取技术需求：按 doc_id 删除旧评分点 + 项目级 sp_derived 衍生需求，保留招标原文技术需求 → 状态重置 uploaded → 入队 task_parse_tender（score_points_only=True，LLM schema 裁掉 tech_requirements）；仅 tender_file；parsing/uploaded 状态拒绝 4010；非招标文件 4010；文档不存在 4004；审计 document.reparse） |
| GET | /projects/{pid}/score-points | 评分点列表（可 PUT 单条确认/改 strategy） |
| POST | /projects/{pid}/requirements/generate | 基于已确认评分点梳理技术需求（body.score_point_ids 省略→全部 confirmed 评分点，显式传→勾选梳理；LLM 提炼+sp_id 映射回填；幂等覆盖旧 sp_derived；无评分点 4004；审计 requirements.generate） |
| GET | /projects/{pid}/requirements | 技术需求列表（LEFT JOIN score_points 携带 related_sp；only_mapped=true 仅返回已映射需求） |
| GET | /projects/{pid}/benchmark | 评分对标报告 |
| POST | /projects/{pid}/generate | 触发方案生成（返回 task_id） |
| POST | /projects/{pid}/workflow/start | 启动方案生成工作流（API 进程后台任务推进，遇 HITL interrupt 停下；在途重复启动被拒 4009） |
| GET | /projects/{pid}/workflow/status | 工作流状态（phase/progress/interrupt/score_points/outline/chapters/error） |
| POST | /projects/{pid}/workflow/confirm-score-points | 确认评分点，resume 工作流进入大纲阶段（前置校验 interrupt 类型） |
| POST | /projects/{pid}/workflow/confirm-outline | 确认大纲（2026-08-16 二次编辑增强：body.outline 为前端编辑后大纲、body.mounted_doc_ids 为资料库挂载配置，两者均经 **resume payload** 传给 confirm_outline 节点——不再走 update_state 写 state，避免清除 checkpoint pending interrupt；缺省不携带时保持原大纲/项目全量检索），节点内替换 state.outline 并落库 proposal_skeletons，resume 进入章节生成 |
| POST | /projects/{pid}/workflow/regenerate-outline | 重新生成大纲（仅 confirm_outline interrupt 挂起时允许；resume 节点 action=regenerate 返回图边标记，经 confirm_outline → generate_outline → confirm_outline 回边重新生成（节点返回值写入 checkpoint，state 与 DB 落库一致），随后再次 interrupt 挂起，保留 pending interrupt） |
| PUT | /projects/{pid}/workflow/outline-draft | 保存大纲二次编辑草稿（body.outline 编辑后大纲、body.mounted_doc_ids 挂载配置；upsert proposal_skeletons.draft/draft_updated_at；仅项目成员；审计 workflow.outline_draft_save） |
| GET | /projects/{pid}/workflow/outline-draft | 读取草稿（返回 {outline, mounted_doc_ids, updated_at}，无草稿返回 404；前端进入编辑态拉取，有草稿弹恢复弹窗） |
| DELETE | /projects/{pid}/workflow/outline-draft | 清除草稿（幂等，draft=NULL；审计 workflow.outline_draft_clear；confirm_outline 确认成功后节点自动调用） |
| POST | /projects/{pid}/workflow/confirm-review | 审阅确认：approved → 导出；feedback → 章节重写后复审 |
| POST | /projects/{pid}/workflow/rewrite-chapter | 按审阅意见重写指定章节（query 参数 chapter_no、comment） |
| GET | /projects/{pid}/workflow/export | 导出 Word（返回导出状态与存储 key） |
| GET | /projects/{pid}/skeleton | 方案骨架 |
| GET | /projects/{pid}/sections | 章节列表（含状态/内容） |
| PUT | /projects/{pid}/sections/{sid} | 章节编辑（人工直接改） |
| POST | /projects/{pid}/sections/{sid}/review | 审阅动作（approve/rewrite+意见） |
| POST | /projects/{pid}/export | 导出 Word（返回下载 URL） |
| GET | /tasks/{tid} | 任务进度轮询 |
| GET | /users | 用户列表（三期：**仅管理员** role=admin 或白名单；查询参数 keyword（邮箱/姓名 ilike）/role 枚举过滤/page；返回 email/display_name/role/created_at，不含 password_hash） |
| PUT | /users/{user_id}/role | 角色变更（三期：**仅管理员**；role ∈ member/kb_admin/admin；不可变更自己 4000；降级 admin 时至少保留 1 名 admin 4000；审计 user.role_change 记 from/to） |
| GET | /audit-logs | 审计日志查询（三期：**仅管理员**，只读；过滤 action 前缀匹配/user_id/project_id/target_type 精确/时间范围 start-end；created_at 倒序分页，LEFT JOIN users 返回 user_name；查询自身记审计 audit.query） |

**前端 HITL 交互契约**（2026-08-16 补）：所有 confirm 端点均校验 pending interrupt，前端不得直接调用，须先确保工作流停在对应 interrupt：
- 招标解析页（ParseView 内嵌 ParseConfirmView）：「确认并生成大纲」先 GET workflow/status，无挂起 interrupt 则 POST workflow/start，轮询（1s×60）直到 interrupt.type=confirm_score_points 再调 confirm-score-points；state.error 非空时展示解析失败原因。**短路引导（2026-08-16）**：status 已挂起其他类型 interrupt（大纲确认/章节审阅）或 phase 已推进到 outline 之后（generate/review/done）时，不重复 start（在途重复启动被后端 4009 拒绝）也不盲等，立即提示「工作流已进入后续阶段，请前往方案生成页继续操作」；phase=confirm 无 interrupt 时（parse 节点刚完成、interrupt 即将挂起）仅轮询等待不 start。页面存在 uploaded/parsing 状态招标文件时每 5s 自动轮询解析状态。
- 方案生成页（GenerateView）按 workflow/status 三态呈现：① phase=init 或停在 confirm_score_points → 引导回招标解析页；② 已启动但 outline 为空 → 大纲后台生成中，每 2s 轮询 status（上限 4 分钟）；③ interrupt=confirm_outline → 展示大纲（每章标注覆盖评分点条款号 covered_clauses）、资料库挂载配置与「大纲编辑」卡片（**树形编辑**：递归树形结构，章节编号 1/1.1/1.1.1 按位置自动重算，支持增删子节/上下移/升降级（≤4 层）/改标题与覆盖评分点；**左侧大纲树** a-tree 与编辑区实时同步，生成态展示大纲章节+子节），**草稿保存**（防抖 2s 自动 PUT outline-draft + 手动保存 + 刷新后 GET 拉取弹恢复弹窗，confirm-outline 确认成功后自动清除），操作按钮：「重新生成大纲」（popconfirm 确认后调 regenerate-outline，完成后自动刷新）与「确认并生成」（primary，即 confirm-outline，携带编辑后 outline + mounted_doc_ids；前端先校验至少 1 章且标题非空）。章节生成期间除 WS 流式事件外，每 3s 轮询 status 兜底（progress≥0.75 或 phase=review/done 视为完成，防 WS done 事件丢失后页面永久停留在生成中）。前端失败提示透出后端 BizError message。

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
graph.add_node("write", write_node)            # 撰写章节（三期：真流式，on_delta 节流发 section_token）
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

**大纲节点输出契约（2026-08-16 增强）**：`generate_outline_node` 的 LLM 响应 schema 为 `{"chapters": [{chapter_no, title, sections, covered_clauses}]}`，`covered_clauses` 为本章节关联的评分点条款号数组（必填，可为空数组——前置章节如项目概述无关联条款；骨架章节不得为空），用于评分点覆盖校验与追溯。提示词正文（prompts/outline.yaml，2026-08-16 两次优化）：**核心章节按最终定稿骨架模板组织**（顺序与命名保持，子节由技术需求推导）——①需求分析（按性能/信创/安全/对接/实施交付类别归纳全部技术需求）②业务流程设计（巡检/告警处置/数据流转等）③总体架构设计（架构、选型、信创适配、性能指标支撑）④详细功能说明（功能类需求逐项实现要点）⑤对接方案（外部系统与设备接口/协议/联调）⑥培训与运维服务方案（培训、运维保障、实施交付）；无对应技术需求内容时允许精简合并相关章节，可补充项目概述等前置章节。**技术需求为核心唯一依据填充章节内容**——全部技术需求完整映射无遗漏；**评分点仅作追溯辅助**（covered_clauses 标注），不得以评分项/分值划分章节，不得直接采用评分项名称作为章节标题，无对应技术需求的评分项并入最相关章节；user_prompt 中技术需求优先于评分点呈现。大纲整段（含 covered_clauses）随 `proposal_skeletons.tree` JSONB 持久化，下游 confirm-outline HITL 可读取并编辑。

**大纲二次编辑（2026-08-16）**：`confirm_outline_node` 的 resume payload 支持 `outline`（编辑后大纲：替换 state.outline 并落库 `proposal_skeletons`，DB 与 state 一致，随后进入章节生成）与 `mounted_doc_ids`（挂载配置写入 state）；两者由 API 层直接放入 resume payload 传递，**不经 update_state**（`aupdate_state` 会清除 checkpoint pending tasks，导致 interrupt 丢失后工作流 4009 卡死——2026-08-16 实测缺陷）。

**草稿联动与嵌套 sections**（2026-08-16）：① `confirm_outline` 确认成功后调用 `_clear_outline_draft` 清除 `proposal_skeletons.draft`（防陈旧草稿下次进入编辑态误恢复）；② `retrieve_node`/`generate_chapter` 经 `flatten_sections` 兼容大纲 sections 两种形态——字符串数组（`["背景","政策"]`）与嵌套树（`[{title,children}]`），递归推导编号 1/1.1/1.1.1 并扁平化为子节列表，前端树形编辑（嵌套 children）与后端扁平消费（string[]）解耦；③ 草稿三函数（save/get/clear）实于 `workflow_runtime`，API 三端点（PUT/GET/DELETE outline-draft）含审计埋点，前端防抖 2s 自动保存 + mounted_doc_ids 随草稿一并存取。

**重新生成大纲**：`workflow_runtime.regenerate_outline` 仅允许 confirm_outline interrupt 挂起时调用（先经 ensure_pending_interrupt 校验，否则 4009）；实现为 resume confirm_outline 节点（resume 值 `{"action": "regenerate"}`）返回图边标记 `regenerate_requested`，经 `outline_route` 条件边（confirm_outline → generate_outline → confirm_outline 回边）重新生成并落库 `proposal_skeletons`，**节点返回值正常写入 checkpoint**（state.outline 与 DB 一致），随后再次 interrupt 挂起（保留 pending interrupt，前端可继续确认，支持多次重新生成）；确认（True/confirmed）后清除标记返回进入章节生成。历史缺陷：曾内联调用 generate_outline_node（普通函数返回不经图，checkpoint 仍旧大纲、DB 已新大纲），确认后章节按旧大纲生成——2026-08-16 已改图边路由根治（回归样本验证）。异常经 BizError 5011 透出。

### 6.2 HITL 与中断恢复

- `review_node` 内调用 `interrupt({section_id, content_md, score_points})`；
- 用户通过 / 编辑 / 重写后 `Command(resume=...)` 恢复执行（resume 前校验 pending interrupt 类型匹配，不匹配拒绝）；
- Checkpointer：`PostgresSaver` 持久化，`thread_id = project_id`，支持任务中断后从断点续跑；
- 资料库挂载（二期）：`confirm-outline` 将 `mounted_doc_ids` 经 resume payload 传给节点写入 state（None=项目全量检索；空列表=明确不挂载），`retrieve_node`/`write_node` 读取并透传 `doc_ids` 给 `retrieve_similar`/`generate_chapter`，限定 RAG 检索范围；
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
| 骨架规划器 | 技术需求（核心）+评分点（追溯） | 章节树 JSON | 定稿骨架模版（2026-08-16 广东施组定稿）：需求分析/业务流程设计/总体架构设计/详细功能说明/对接方案/培训与运维服务方案 六章，顺序命名保持；技术需求全映射无遗漏；评分点经 covered_clauses 追溯、禁止评分项名称作章节标题 |
| 章节撰写器 | 章节计划+检索素材+前文摘要 | Markdown 正文 | 只用检索素材、参数不低于★要求；「详细功能说明」类章节按模块固定结构撰写（系统概述→需求设计→功能架构→核心功能点[功能说明/界面设计/业务流程设计]） |
| 校验器 | 正文+评分要求 | pass/fail+issues | 必答要点/字数/参数检查 |
| 批注重写器 | 原文+反馈+素材 | 重写后 Markdown | 仅改反馈涉及内容 |

**大纲定稿模版说明**（2026-08-16 依《广东施组模版》固化，提示词层实现，schema 不变）：
- **总体架构设计**章：sections 固定为 设计思路/设计原则/设计目标/总体架构图/功能模块图/数据架构/技术架构/业务架构/安全架构 九子节（顺序保持）；
- **详细功能说明**章：sections 为功能模块列表（模块名由技术需求推导，如“一张图模块”“巡查管理模块”，每模块一项）；模块内部结构（系统概述/需求设计/功能架构/核心功能点，功能点含功能说明/界面设计/业务流程设计）由章节撰写器展开；
- 其余骨架章（需求分析/业务流程设计/对接方案/培训与运维服务方案）子节由技术需求推导；无对应需求内容允许精简合并，骨架顺序与命名保持，可在核心章节前补充项目概述等前置章节；
- 回归样本（output/verify_outline_prompt3.py，项目 5477db96）实测：7 章 = 项目概述 + 六骨架章全命中且顺序一致、总体架构 9/9 子节、详细功能说明 5 模块、评分项不单独成章、covered_clauses 骨架章节全非空。

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
  → pgvector cosine 召回 Top-K=30（RERANK_RECALL_K，限定该用户可见 doc 集合）
  → 云端 Rerank 精排（DashScope gte-rerank 兼容协议，按 relevance_score 降序）
  → 截断返回 Top-8 素材给撰写节点
```

接入点：`rag_service.retrieve_with_rerank()` 统一入口，`retrieve_node`（章节撰写检索）、`search_materials`（资料检索端点）、`chapter_service` 兜底检索均已接入；纯向量 `retrieve_similar` 保留作为召回层。

**Rerank 降级矩阵**（`rerank_service.rerank`，一律返回原向量序、不抛异常、不阻塞检索）：

| 场景 | 行为 |
|---|---|
| LLM mock 模式 | 直通原序（保持 E2E 确定性） |
| `BID_RERANK_ENABLED=false` 或未配置 `BID_RERANK_API_KEY` | 直通原序（不外发） |
| 空候选 | 直通空列表 |
| API 超时（10s）/HTTP 错误/响应结构非法/index 越界 | 降级原序；越界 index 忽略，未覆盖候选按原序补尾 |

配置项（env）：`BID_RERANK_ENABLED`、`BID_RERANK_API_BASE`（默认 DashScope text-rerank 端点）、`BID_RERANK_API_KEY`、`BID_RERANK_MODEL`（默认 `gte-rerank`）。安全：查询与候选文本外发前经 `redact()` 脱敏；api_key 仅入请求头，不入日志/明文。

### 7.3 质量兜底

- 检索为空 → 提示"资料库无相关内容"，撰写节点降级为基于通用知识撰写并标记"待人工补充"；
- 引用溯源：写入 `proposal_sections.citations`，导出时标注 `【来源：XX P12】`；
- Reranker 已引入（云端 API，见 7.2 降级矩阵）；评测集仍留待后续（用人工确认页兜底）。

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
