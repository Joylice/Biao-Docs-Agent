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
- 简单账号登录 + 项目级隔离（权限模型：RBAC 功能权限 + 项目成员表数据范围，双维正交，2026-08-17 完整落地，见 §九）；
- 真实资料批量入库与向量检索（RAG 底座，含云端 rerank 精排与离线评测框架）；
- 招标文件解析（PDF/Word → 评分点/★条款/资格要求结构化提取）；
- 评分点对标分析；
- 方案骨架生成与章节内容生成（含校验）；
- 章节级人工审阅反馈与局部重写（不做行内批注/diff）；
- 流式输出；Word 文档导出（固定模板）。

**范围外（二期）**：版本管理与 diff、多模型路由降级、OCR 扫描件、商务/报价标生成、私有化部署。（Reranker 精排、离线评测框架与完整 RBAC 已提前落地，见 §7.2 / §10.3 / §九）

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
- 双维正交权限模型：**功能权限**（RBAC：`users.role` → `roles`/`permissions`/`role_permissions` → 6 权限点 system:manage/kb:manage/kb:read/kb:upload/settings:read，全局，`require_permission` 依赖判定）＋ **数据范围**（`project_members` 表 / `owner` 属性，项目内，`_check_project_member` 先行校验，再按需走权限点/owner 校验）；
- 项目成员两级（owner/协作者）：创建者为 owner 自动入成员表，owner 可添加/移除协作者（仅 email 加入，MVP 不做项目内角色细分）；
- 中间件统一校验 JWT 与项目权限（WebSocket 握手同样强制，close code 4001/4003）。

**核心流程**：注册/登录 → 创建项目 → 邀请协作者（MVP 仅按 email 加入）→ 进入项目工作台。**成员管理（2026-08-17）**：工作台「成员管理」抽屉展示成员列表（email/display_name/加入时间/owner 标记，owner 恒在首位，项目成员即可见）；「移除」popconfirm 仅 owner 可见（移除 owner 本人 4000「不能移除项目所有者」、自移 4000、目标非成员 4004）；「添加协作者」表单并入同一抽屉（仅 owner 可操作）。

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

**多知识库容器与可见性矩阵（2026-08-18）**：`knowledge_bases` 容器表（scope=`personal|project|company`）作为 kb_material 的分组与授权容器，不改变分块/向量链路；`documents.kb_id` 标记素材归属（迁移 0014，存量全局素材 kb_id=NULL 兼容）。可见性矩阵：company 全员可见；project 限该 project_id 成员；personal 仅 owner_id 本人。建库权限：personal 任意登录用户、project 仅该项目 owner、company 仅 kb_admin/admin；删库限创建者（company 库限管理员），库内素材一并删除（MinIO + 记录 + 分块 CASCADE）。素材上传 `POST /kb/materials` 增可选 Form 字段 `kb_id`（校验库存在且当前用户可写）。挂载改库级：confirm-outline/outline-draft 增 `mounted_kb_ids`（与 mounted_doc_ids 并集生效），retrieve_node 经 `kb_base_service.resolve_doc_ids` 库→素材 id 列表传入检索；AI 辅助生成检索范围 = 项目挂载 ∪ 本人个人库素材（见 §3.9）。

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
   - format_requirements（2026-08-18）：`[{category, requirement}]`，仅提取格式/排版类条款（字体字号、行距、页边距、纸张、装订、页码、目录等），排除评分点与技术需求；category 枚举 `font_body|font_heading|line_spacing|margin|page_setup|binding|page_number|toc|other`，未知分类入库时归 `other`、空 requirement 条目丢弃
5. 人工确认页：解析结果表格化展示，可增删改；确认后落库、状态置 `parsed`。

**格式要求存储与编辑（2026-08-18）**：提取结果写入招标文件 `documents.meta.format_requirements`（不建新表）；解析确认页评分点上方「格式要求汇总」卡片按 category 分组展示并支持增删改，PUT 幂等整体覆盖（审计 `document.format_requirements_update`）；仅 tender_file 可读写，其余 doc_type 拒绝（4010）。该数据驱动 Word 导出排版（见 §3.7）。

**校验**：提取结果二次回读原文核对（LLM 自检 + 关键字段（★条款数）人工确认）；非法 JSON 自动重试 ≤2 次。

**实现约束（2026-08-16）**：文本抽取实现为 pdfplumber（PDF）/ python-docx（段落 + 表格，按文档顺序）；送 LLM 前先经 `select_parse_window` 选取窗口（预算 4 万字符）再脱敏：封面头部 + 评分细则区锚定窗口（细则关键词优先于“评标办法前附表”等汇总性锚点）+ 技术要求区锚定窗口——仅固定截前 N 字符或锚定前附表会让评分细则/技术需求落窗外，导致提取为空或“详见招标文件”类笼统描述。

**表**：`documents`（status: uploaded→parsing→parsed→confirmed）、`score_points`、`tech_requirements`。

**技术需求梳理（评分点确认后，2026-08-16）**：人工确认要响应的评分点后，`POST /requirements/generate` 经 LLM（prompts/requirements.yaml）从评分项内容（item+criteria+分值+星级）提炼可验证的技术需求并回填映射（tech_requirements.sp_id）。映射键为评分点唯一标识 `clause_no|item`（同一条款号下可能存在多个评分项，仅用 clause_no 会互相覆盖；LLM 仅写条款号且唯一时降级容错）。幂等：同项目重复梳理先删旧 sp_derived 再重建，招标原文提取的需求（source 为 NULL/tender）不受影响；seq 从存量最大值续编。重新解析（reparse）只负责评分点提取：清除旧评分点与 sp_derived 衍生需求，保留招标原文技术需求，并以 score_points_only=True 入队（worker 解析 schema 裁掉 tech_requirements，不重复提取）；前端入口唯一，位于确认页评分点卡片操作区（与批量修改策略/一键全确认并列，最右侧）。

### 3.4 评分对标分析模块

**职责**：基于评分点生成对标报告，指导撰写优先级。

**对标表字段**：`clause_no / item / score / criteria / strategy / referenced_material / risk_level(high|mid|low)`。

**风险分级算法**（阶段 D 落地，`benchmark_service`）：`risk = f(score, coverage)` —— score ≥ 6 且 coverage < 0.3 → high（分值高且资料库无对应素材，提示售前补资料）；score ≥ 3 或 coverage < 0.6 → mid；其余 low。coverage = item+criteria 检索命中数 / top_k(5)；mock 模式走 sha256(query) 确定性规则（可复现），检索异常降级 0.0。输出按 `score × (1 - coverage)` 降序，供前端排序展示。

**读写契约**（阶段 D）：GET benchmark 懒计算 coverage/risk 并回写 `score_points.risk_level`；PUT 仅 owner 编辑 strategy（≤2000 字，审计 benchmark.strategy）。

**高风险策略注入生成**（阶段 D 1.4）：write_node 生成章节前读取 confirmed 且 risk_level=high 的评分点（strategy 缺失回退 item；mock 无记录时注入确定性样本 MOCK-HR），脱敏后渲染为「- 条款号: 策略」行，经 chapter.yaml `{benchmark_high_risk}` 段注入章节提示词，要求本章针对性正面响应；回归样本 output/verify_benchmark_prompt.py。

**输出物**：Web 内联对标表（GenerateView「评分对标」卡片：条款号/评分项/分值/判定标准/coverage 进度条/risk 标签/strategy 失焦保存，非 owner 只读）+ 导出附表（随 Word 导出）。

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
    glossary: list[dict]                 # 术语表（阶段 E2：{term, canonical, desc}）
    retrieved_citations: dict[str, list[dict]]  # 阶段 E3：chapter_no -> 引用溯源列表
    output_docx_path: str | None
```

**上下文管理**：全局只保留 skeleton + 每章摘要；每章独立窗口生成，注入「前文摘要 + 本章评分要求 + RAG 检索素材 + 术语表」。

**HITL 设计**：每章 `write` 完成后节点 `interrupt()`，等待用户「通过/改稿/重写」；Checkpointer（Postgres）持久化图状态，支持任务中断后恢复。

**校验节点**：必答要点清单（该章对应 score_points 是否全部应答）、字数下限、★参数不低于招标要求；失败自动重写 ≤2 次。**参数比对校验落地（阶段 E1）**：`validate_node` 接入 `param_check_service.check_chapter_params`——正则断言抽取招标★条款中的参数要求（≥/≤/不低于/至少 等）与章节正文对应数值（万/亿单位归一化后比对），规则比对不确定时 LLM 兜底判定；mock 模式与 LLM 异常一律降级返回空 issues（不阻塞流程）；产出的 issues 并入校验失败原因走既有 write 重试链路。**废标拦截（阶段 H）**：`validate_node` 追加废标条款校验——正文触碰已人工确认的 severity=high 红线条款（分类关键词/标题前缀规则比对，见 §3.12）即追加「废标风险」issue 并在节点输出标记 `disqualification_risk`，走既有重试链路；比对异常降级放行。

### 3.6 人工审阅与重写模块

**职责**：章节级审阅，反馈后局部重写，形成新版本。

**MVP 交互**：
- 审阅页：左侧章节树 + 右侧 Markdown 渲染（预览）；
- 每章操作：通过 / 编辑（直接改正文）/ 反馈重写（输入修改意见）；
- 编辑与反馈均写入 `reviews` 表 → 触发 `rewrite` 节点仅重写该章（携带原文 + 反馈 + 检索素材）；
- 人工编辑保存（2026-08-17）：编辑态「保存」调 PUT workflow/sections/{chapter_no} 直接落库（state 与 proposal_sections 双写、摘要重算），成功清除本地草稿；章节列表 tag 区分「已修改」（本地草稿未保存）/「待审」/「待重写」，提醒保存；与「反馈重写」并存互不覆盖；
- 版本：MVP 不做版本表，重写即覆盖 + `updated_at` 留痕；批注历史保留在 reviews 表（可追溯）。

### 3.7 文档导出模块

**职责**：方案 Markdown → 标书模板 .docx。

**渲染流程**：Markdown → 结构树（标题层级/表格/列表）→ python-docx 按模板样式写入 → 目录域（打开自动更新）→ 页码/分页。

**MVP 模板**：单套公司标准模板（封面 + 目录 + 正文样式 + 附表：评分对照表、资质索引表）。

**格式要求驱动排版（2026-08-18）**：导出节点读取最新 tender_file 的 `meta.format_requirements`，经 `format_spec.py` 解析为 docx 参数（正文字体/字号、标题字号、行距、页边距）；内置中文字号映射（小四→12pt、四号→14pt、小三→15pt 等）与行距/边距解析；无法识别项回退默认样式（正文 12pt、行距 1.5、默认页边距），不阻塞导出；读取格式要求失败时降级默认排版。

**导出结构增强（阶段 E4）**：`export_to_word` 新增可选参数 `company_name / benchmark_rows / citations_by_chapter`（均缺省兼容旧调用）：① 封面页（项目名居中大标题 + 公司名 + 编制日期，公司名取 `settings.company_name`/BID_COMPANY_NAME）后分页；② 「目录」标题 + TOC 域（`TOC \o "1-3" \h \z \u`，fldChar begin/separate/end，Word 打开自动更新）；③ 页脚 PAGE 域页码（居中）；④ 章节标题 `page_break_before` 章前分页；⑤ 评分对标附表（「附表 评分对标一览」：条款号/评分项/分值/覆盖度/风险/应对策略，数据来自 `benchmark_service.build_benchmark`）；⑥ 引用溯源标注——章末追加 `【来源：{doc_title} P{page_no}】` 行（数据来自 `proposal_sections.citations` 按章首编号聚合）。export_node 读取引用/对标数据失败时降级不附加，不阻塞导出。

### 3.8 流式输出模块

**职责**：章节生成内容实时推送前端。

**设计**：FastAPI WebSocket（`/ws/{project_id}`）；节点生成时经 Redis pubsub 发布事件（`bid:events:{project_id}`），WebSocket 端点订阅并转发前端；前端流式渲染；断线重连后拉取已生成缓存（sections 已落库）。**用户级推送（阶段 C，2026-08-20）**：`/ws/user/{user_id}` 订阅 `bid:user:{user_id}`，分工事件定向推送相关用户（assign→assignee、submit→owner、review→assignee、confirm-outline→全员 workbench_refresh），WorkbenchView 收事件静默刷新待办（指数退避重连 ≤5 次）。

**事件协议**（`event_service.py`，前后端统一）：

| 事件 | 负载 | 说明 |
|---|---|---|
| `progress` | `{phase, progress, current_chapter}` | 阶段进度（outline/generate/review） |
| `section_token` | `{chapter_no, delta, source?}` | 三期真流式增量文本块（write_node 节流发布：累积 ≥40 字符或距上次 ≥200ms 取先到者；尾部缓冲兜底 flush，delta 拼接 == 全文；2026-08-18：辅助生成发布时带 `source="assist"` 区分整章工作流生成） |
| `section_done` | `{chapter_no, title, content, source?, stopped?}` | 章节完成（携带全文，供断线重连/丢块兜底对齐；辅助生成携带 `source="assist"` 与 `stopped` 暂停标记） |
| `task_done` | `{export_storage_key}` | 全流程完成 |
| `task_assigned` | `{chapter_no, assignee_id}` | 分工推送（2026-08-18：owner 分配章节后通知成员） |
| `task_submitted` | `{chapter_no, assignee_id}` | 成员提交章节待审（2026-08-18） |
| `task_reviewed` | `{chapter_no, assignee_id, action}` | owner 审核通过/打回（2026-08-18） |
| `workbench_refresh` | `{project_id}` | 工作台刷新通知（阶段 C：仅用户级频道，confirm-outline 后推送全员） |
| `error` | `{message}` | 异常 |

**三期真流式链路**（已实现）：`llm_service.call_llm_stream`（mock 模式将 _MOCK_TEXT 按 ~20 字切片 yield；真实模式 `acompletion(stream=True)` 逐 chunk yield delta，出口同 call_llm_text 脱敏）→ `chapter_service.generate_chapter(on_delta=...)` 逐块回调并累积全文（未传 on_delta 时保持非流式，向后兼容）→ `write_node` 经 on_delta 节流发布 `section_token`，结束后照旧落库 + `section_done`（全文）+ `progress`；前端 GenerateView 对 `section_token` 增量追加渲染（已移除假打字机定时器），`section_done` 全量覆盖对齐。

**LLM 结构化输出供应商兼容**（三期验收修复）：DeepSeek 兼容接口不支持 strict `json_schema`（报 "This response_format type is unavailable now"），`call_llm_with_schema` 内置 `_compat_response_format`：deepseek 模型自动降级为 `{"type":"json_object"}` 并将 schema 结构写入 system prompt 约束输出；其余模型（如 qwen）保持 json_schema 原样透传。

**握手鉴权**（实现于 `app/api/websocket.py`）：连接 URL 携带 query 参数 `token`（JWT access token）；服务端在握手阶段校验 token 有效性与项目成员资格，失败即关闭连接（close code `4001` 未认证 / `4003` 非成员），不发送任何业务消息；refresh token 一律拒绝。

### 3.9 章节分工协作模块（2026-08-18）

**职责**：方案大纲确定后的章节分工流——owner 分配章节给成员、推送任务、成员 LLM 初稿 + 人工编制、提交汇总、owner 审核（通过/打回）。

**状态机**（`chapter_assignments.status`）：`pending（已分配待接收）→ in_progress（编制中）→ submitted（已提交待审）→ approved（通过）/ rejected（打回，回退可重新领取重编）`。

**流程与规则**：
1. 分配：仅 owner，批量 `[{chapter_no, title, assignee_id}]` 幂等 upsert；assignee 必须是项目成员（非成员 4004）；推送 `task_assigned`。
2. 领取/编制：仅 assignee 可 accept（pending/rejected → in_progress）；「生成初稿」复用 chapter_service.generate_chapter（RAG + 脱敏 + mock 降级），回写 state.chapters 与 proposal_sections（status=draft）；人工编辑走 PUT workflow/sections/{chapter_no}（受章节级权限约束）。
3. 提交：仅 assignee，in_progress → submitted，推送 `task_submitted`。
4. 审核：仅 owner，approved → approved；rejected → rejected 附意见（review_comment），推送 `task_reviewed`；审计 `division.review`。

**章节级「可视不可改」**：所有项目成员可读全部章节；已分配章节仅 assignee/owner 可编辑（save_section_edit 前置校验 `division_service.check_chapter_editable`，越权 403）；**无任何分工的章节仅 owner 可编辑**（2026-08-20 收紧，废弃「未分配成员可编辑」兼容）。分工表只跟踪负责人与状态，章节正文仍存 workflow state `chapters` + `proposal_sections`，不重复存储。

**前端**：Workspace 子路由「分工协作」（步骤 4）：owner 视角章节列表 + 成员下拉分配 + 增量推送 + 审核弹窗（打回必填意见）；成员视角任务卡片 + 领取/生成初稿/内嵌编辑器/提交；状态徽标按 status 渲染；监听 WS `task_*` 事件自动刷新。分工表附 outline 子节（list 接口附 `sections` 与 `submitted_by_name`），前端树形展示 2 级目录（章行保留分配/状态控件，子节行缩进纯展示，分工粒度仍为章级）。

**章节编制工具栏（2026-08-18）**：编辑器 modal 改近全屏抽屉，工具栏：AI 生成/人工编辑（开关）/关闭编辑/图片/保存/提审/批注。
- **AI 辅助生成**（`assist_service`）：仅 assignee，`POST /chapter-assignments/{id}/assist-generate`（body `{prompt, mode: append|overwrite}`）；检索范围 = 项目挂载（库级 ∪ 文档级）∪ 本人个人库素材；上下文 = 前文摘要 + 本章评分点 + 技术需求 + 用户 prompt；复用 generate_chapter 的 on_delta 流式经 WS `section_token`（source=assist）推送；append 追加到现有正文末尾/overwrite 整章覆盖，落库复用双写口径（state.chapters + proposal_sections + 摘要重算）；prompt 与检索素材外发前 redact 脱敏。
- **暂停机制**：`call_llm_stream` 支持 `asyncio.Event` 取消令牌（每 chunk 检查，mock 模式同样分段支持）；任务注册表 `project_id:chapter_no → Event`，`POST .../assist-generate/stop` 置位 → 已累积部分按 mode 落库（空部分不落库）+ `section_done`（stopped=true）；暂停仅对辅助生成生效，整章工作流生成不支持暂停。
- **图片插入**：`POST /projects/{pid}/images`（jpg/png/gif/webp ≤10MB，存 MinIO `images/{project_id}/`，返回 storage_key + 签名 URL；GET signed 读限本项目 images 目录防跨项目越权）；前端工具栏上传后在光标处插入 `![名称](url)`，预览态 MarkdownRenderer 渲染；Word 导出（export_service）解析 `![alt](url)` → 拉取 MinIO 字节 → `add_picture` 内嵌（宽度上限 15cm），拉取失败降级为文本说明不阻塞。
- **章节级批注**：`chapter_annotations` 表（迁移 0015，阶段 E5 迁移 0016 补 `updated_at`），`GET/POST /chapter-assignments/{id}/annotations`（项目成员可读，assignee/owner 可写，时间正序，附批注人姓名）；与审核打回意见字段并存；前端编辑器「批注」抽屉（留言列表 + 输入框）。**章节维度批注 CRUD（阶段 E5）**：`GET/POST /projects/{pid}/chapters/{chapter_no}/annotations` 与 `PUT/DELETE .../annotations/{annotation_id}`（`app/api/annotations.py`）——写操作先项目成员校验 + `check_chapter_editable` 口径（无权限 403「无该章节批注权限」），PUT/DELETE 再限批注作者本人或项目 owner；content 1-2000 字；审计 annotation.create/update/delete（target_type=chapter_annotation）；ReviewView 以章级折叠面板懒加载展示与增删改。

**审阅增强与意见回派（2026-08-18）**：ReviewView 左侧 a-tree 全量 2 级目录（章 + 子节，子节仅导航不可选，审阅操作仍章级与生成粒度一致），章卡片标「提交人：XXX」（无分工显示「AI 生成/未分配」）；confirm-review feedback 意见回派：按 chapter_no/标题匹配大纲后查分工，命中且有 assignee → 该 assignment 置 rejected + review_comment + 推送 task_reviewed（assignee 在分工页看到打回可重编），并从 feedback 移除避免重复重写；无 assignee 章节保持现有 rewrite 链路；全部意见均回派后 decision.action 改 `redispatched`（review_route 返回 review 自环，重新 interrupt 等待复审，响应 next_phase=redispatch），避免空 feedback 进入 rewrite 报错。

**子节级分工与审阅下沉（2026-08-20）**：
- **存储下沉**：章节仍整章 AI 生成（保上下文连贯），生成完成后 `chapter_service.split_chapter_to_sections` 按大纲子节标题（`## 标题`）切分为子节行写入 `proposal_sections`（section_id=`1.1`，与 flatten_sections 嵌套树编号一致），切分失败残留段并入上一子节不阻塞；`state.chapters` 保持章级全文（检索/摘要用），`proposal_sections` 为子节真源；大纲无子节的章保持章级行（存量兼容）。初稿生成/辅助生成落库路径统一走「章生成 → 子节拆分存储」。
- **子节分配**：`assign_chapters` 接受 `chapter_no="1.1"` 子节粒度；**章级分配自动展开为其全部子节批量分配**（子节清单来自 skeleton tree）；`check_chapter_editable` 改**最小粒度匹配**——子节有分工则仅该子节 assignee/owner 可编辑该子节，章级分工覆盖其下子节。
- **树形分工列表**：GET chapter-assignments 返回章行附 `children`（子节分工）与聚合字段 `approved_count/total`，前端树形渲染。
- **审阅下沉**：accept/submit/review 端点对子节 assignment 生效；自动快照触发按**最细粒度**判定（无任何 pending/in_progress/submitted 且 ≥1 approved）；confirm-review 意见回派匹配支持子节编号/标题。
- **自然序导出**：export_service 读 proposal_sections 按自然序排序（`1.1 < 1.2 < 2`，修复字典序 `10 < 2` 隐患）。

**表**：`chapter_assignments`（迁移 0013，chapter_no String(32) 天然支持 `1.1` 子节编号）、`chapter_annotations`（迁移 0015）。

### 3.10 方案版本库与归档模块（2026-08-18）

**职责**：评审通过方案入版本库（下载查阅）与归档公司知识库供检索。

**版本快照**（`version_service`）：`proposal_versions` 表（迁移 0015，UNIQUE(project_id,version)，version 续号）；快照 = 导出 Word（复用 export_to_word，含格式要求排版）+ Markdown 源（章/子节结构重建）双产物入 MinIO `versions/{project_id}/`；**结构化快照（阶段 E5，迁移 0016 加 `snapshot_json`）**：快照同时落 `{outline, chapters}` JSON，供版本回滚。**版本回滚（阶段 E5）**：`POST .../versions/{id}/rollback`（仅 owner）——按 `snapshot_json` 回写章级 `proposal_sections`（content_md + status=draft，缺失章节按大纲标题新建）并经 `workflow_runtime.update_state` 同步图状态；无结构化快照的旧版本 400「仅支持 E5 后创建的版本」；审计 version.rollback。**自动触发**：division 审核 approved 后 `maybe_auto_snapshot` 检查「无 pending/in_progress/submitted 且至少 1 章 approved」即快照（created_by=NULL 标记自动，失败 rollback 不阻塞审核）；owner 可手动 `POST /projects/{pid}/versions`（附可选备注）。下载：`GET .../versions/{id}/download?type=docx|source` 返签名 URL。

**归档**：`POST .../versions/{id}/archive`（仅 owner，body kb_id 限公司级库否则 400）：创建全局素材记录（documents：project_id=NULL、doc_type=kb_material、kb_id=目标库、标题「归档-{项目名}-v{n}」，project_id=NULL 保证 kb/search 全局检索可命中）+ 审计 proposal.archive + 入队现有 index 任务分块向量化；归档文档删除不影响版本记录。

**前端**：ReviewView 底部「版本库」卡片：版本列表（版本号/自动快照标记/备注/创建人/时间）+ 手动快照弹窗（owner）+ 下载 Word/Markdown 源 + 归档选库弹窗（仅列公司级库）；**阶段 E5**：版本行追加「回滚」danger 按钮（仅 owner，Modal.confirm 二次确认「将用该版本快照覆盖当前全部章节且状态回退草稿」，成功后刷新版本列表/工作流状态/清空本地草稿）+ 章节批注折叠面板（懒加载、作者/owner 可编辑删除、403 权限提示）。

**表**：`proposal_versions`（迁移 0015）。

### 3.11 工作台模块（2026-08-20）

**职责**：登录后默认首页（顶层路由 `/workbench`，原项目列表移至 `/projects`），单端点返回双视图数据。

**后端**：`GET /workbench/summary`（登录即可，`app/api/workbench.py`）基于 chapter_assignments + proposal_workflows 聚合三查询：
1. 我名下分工（assignee_id=当前用户，JOIN Project 取项目名）→ **任务分桶**（pending 待领取/in_progress 编制中/rejected 被打回/submitted 已提审/approved 已通过，条目含 assignment_id/project_id/project_name/chapter_no/title/status）+ **我的参与项目聚合**（每项目 total/approved/percent/status 分布，percent = round(approved/total×100)，项目 phase 附注）；
2. owner 名下项目（Project.owner_id=当前用户）的分工汇总（复用口径）；
3. owner 名下项目的 submitted 分工 → **待审核清单**（owner_review_pending，非 owner 返空）。

**前端**：`WorkbenchView.vue` 双视图——所有人见「我的待办」分桶卡片（点击直达对应项目分工页 `/projects/{pid}/division`）与「我参与的项目」进度；owner 追加「项目进度」看板（进度条 = approved/总节数 + 状态分布 statistic）与「待我审核」清单；空态友好提示。侧边导航「工作台」置顶。

### 3.12 废标条款识别模块（2026-08-20，阶段 H）

**职责**：从招标文件识别触发废标/否决投标的红线条款，人工确认后贯穿校验与导出链路（P0 竞品核心能力）。

**数据模型**：`disqualification_clauses` 表（迁移 0017）：`clause_no/title/risk_category/severity/recommendation/confirmed`；risk_category 枚举：qualification_missing（资质缺失）/schedule_exceeded（工期超限）/signature_seal（签章要求）/blind_bid（暗标规则）/format_deviation（格式偏离）/substantive_deviation（实质性偏离）/other；severity：high|mid|low（非法值归 mid，未知分类归 other）。

**提取**：`prompts/parse.yaml` 第 4 类提取（废标/红线条款，含提取约束与字段说明）；`parse_service.ParsedTender.disqualification_clauses` → `save_parse_result` 清洗后写入新表（缺 title 丢弃）。

**服务**：`disqualification_service.py`：`scan_content`（仅 confirmed 条款参与：分类关键词或标题前 4 字命中正文即命中）、`scan_project_sections`（章节聚合，仅 high 条款）、`count_unconfirmed_high`（导出门禁依据）、`check_chapter_content`（validate_node 入口，自建只读会话）。

**拦截链**：① `validate_node` 命中已确认 high 条款 → 追加「废标风险」issue + `disqualification_risk` 标记（见 §3.5）；② 导出门禁：`GET workflow/export` 前置检查未确认 high 条款，存在则 4012 阻塞直至人工确认。

**前端**：ParseConfirmView「废标风险」红色卡片（条款列表 + severity 标签（high 红/mid 橙/low 灰）+ 建议措施 + 「已确认」勾选，变更即全量 PUT 幂等覆盖）；ReviewView 章节命中时卡片顶部红色警告条；GenerateView 存在 high 条款时顶部警告横幅。

**表**：`disqualification_clauses`（迁移 0017；另：alembic_version.version_num 扩至 varchar(64) 以容纳长 revision id）。

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

-- 项目成员（owner + 协作者，无角色细分）
CREATE TABLE project_members (
  project_id  UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  user_id     UUID NOT NULL REFERENCES users(id),
  joined_at   TIMESTAMPTZ NOT NULL DEFAULT now(),  -- 2026-08-17：加入时间（迁移 0012，成员列表按此排序）
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

-- 废标/红线条款（阶段 H，迁移 0017）
CREATE TABLE disqualification_clauses (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id  UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  doc_id      UUID NOT NULL REFERENCES documents(id),
  clause_no   TEXT NOT NULL,
  title       TEXT NOT NULL,
  risk_category VARCHAR(30) NOT NULL DEFAULT 'other',  -- 资质缺失/工期超限/签章/暗标/格式偏离/实质性偏离/other
  severity    VARCHAR(10) NOT NULL DEFAULT 'mid',      -- high|mid|low
  recommendation TEXT,
  confirmed   BOOLEAN NOT NULL DEFAULT false            -- 人工确认后才参与校验拦截
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

-- 章节分工（大纲确定后的编制协作；迁移 0013_chapter_assignments）
CREATE TABLE chapter_assignments (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id     UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  chapter_no     VARCHAR(32) NOT NULL,     -- 大纲章节编号（state.outline[].chapter_no）
  title          TEXT NOT NULL,            -- 章节标题快照
  assignee_id    UUID NOT NULL REFERENCES users(id),   -- 章节负责人（必须为项目成员）
  assigned_by    UUID NOT NULL REFERENCES users(id),   -- 分配人（仅 owner 可分配）
  status         VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending|in_progress|submitted|approved|rejected
  review_comment TEXT,                     -- 打回意见（rejected 时必填）
  assigned_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  accepted_at    TIMESTAMPTZ,              -- 领取时间（pending/rejected → in_progress）
  submitted_at   TIMESTAMPTZ,              -- 提交待审时间
  reviewed_at    TIMESTAMPTZ,              -- 审核时间
  UNIQUE (project_id, chapter_no)          -- 一章一负责人，重复分配幂等 upsert
);

-- 知识库容器（多知识库分级可见性；迁移 0014_knowledge_bases，documents 增 kb_id UUID NULL REFERENCES knowledge_bases ON DELETE SET NULL）
CREATE TABLE knowledge_bases (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id  UUID REFERENCES projects(id) ON DELETE CASCADE,  -- NULL = 非项目库（personal/company）
  owner_id    UUID NOT NULL REFERENCES users(id),              -- 创建者（personal 归属人）
  scope       VARCHAR(10) NOT NULL,                            -- personal|project|company
  name        TEXT NOT NULL,                                   -- 同 scope+owner/project 下唯一（服务层校验）
  description TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 章节批注（章节级留言，与审核打回意见并存；迁移 0015_annotations_versions）
CREATE TABLE chapter_annotations (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id  UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  chapter_no  VARCHAR(32) NOT NULL,        -- 大纲章节编号
  content     TEXT NOT NULL,               -- 批注内容
  created_by  UUID NOT NULL REFERENCES users(id),   -- 批注人（assignee/owner）
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX ON chapter_annotations (project_id, chapter_no, created_at);

-- 方案版本库（评审通过快照 + 归档；迁移 0015_annotations_versions）
CREATE TABLE proposal_versions (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id          UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  version             INT NOT NULL,                  -- 项目内自续号（max+1）
  snapshot_note       TEXT,                          -- 快照备注（手动可填）
  storage_key_docx    TEXT NOT NULL,                 -- Word 产物 MinIO key
  storage_key_source  TEXT NOT NULL,                 -- Markdown 源 MinIO key
  created_by          UUID REFERENCES users(id),     -- NULL = 自动快照（全部章节 approved 触发）
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (project_id, version)
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
| POST | /kb/materials | 全局资料库上传（二期：project_id IS NULL 全局共享；登录可用；审计 kb.material_upload；入队向量化；三期：Form 可选参数 category 枚举校验、tags 逗号分隔字符串，服务端拆分校验 ≤10 个/每个 ≤20 字符；2026-08-18：Form 可选 kb_id 归属知识库，校验库存在且当前用户可写） |
| GET | /kb/materials | 全局资料库列表（仅 project_id IS NULL 的 kb_material；分页 page/page_size；三期：查询参数 category/tag 精确过滤（tag 用 PG JSON 包含 `tags @> '["tag"]'`，tags 为 JSON 列需 cast 为 jsonb 后使用 @>），LEFT JOIN users 返回 uploader_name（created_by 为空时空串），列表项含 category/tags） |
| PATCH | /kb/materials/{doc_id} | 全局素材编辑（三期：**仅资料库管理员** get_current_kb_admin_id；body title/category/tags 均可选，复用上传同套枚举/标签校验；审计 kb.material_update 记录变更字段） |
| DELETE | /kb/materials/{doc_id} | 全局资料删除（三期：**仅资料库管理员** get_current_kb_admin_id（role ∈ kb_admin/admin 或白名单兼容），非管理角色 403；限 project_id IS NULL，项目级文档 4004 隔离；MinIO 文件 + 记录 + 分块 CASCADE；审计 kb.material_delete） |
| GET | /kb/materials/search | 全局资料库检索测试（q 必填，top_k∈[1,20]；仅检索全局资料 doc_ids 范围；返回 {items:[{chunk_id,doc_id,title,content,page_no,score}],total}） |
| GET | /kb-bases | 可见知识库列表（2026-08-18：查询参数 project_id 可选项目上下文；可见性矩阵 company 全员/project 限成员/personal 仅本人；返回 scope/素材数） |
| POST | /kb-bases | 创建知识库（2026-08-18：body {scope, name, description?, project_id?}；personal 任意登录用户/project 仅该项目 owner/company 仅 kb_admin/admin；审计 kb.base_create） |
| PATCH | /kb-bases/{id} | 编辑知识库（2026-08-18：name/description 均可选；写权限按 scope 判定；审计 kb.base_update） |
| DELETE | /kb-bases/{id} | 删除知识库（2026-08-18：写权限按 scope 判定；库内素材一并删除：MinIO + 记录 + 分块 CASCADE；审计 kb.base_delete） |
| GET | /kb-bases/{id}/materials | 库内素材列表（2026-08-18：限可见库，不可见 404；分页，LEFT JOIN users 返回 uploader_name） |
| GET | /projects, POST /projects | 项目列表、创建 |
| POST | /projects/{pid}/members | 添加协作者（仅 owner；审计 project.member_add 记 email） |
| GET | /projects/{pid}/members | 成员列表（2026-08-17：项目成员可见；LEFT JOIN users 返回 user_id/email/display_name/is_owner/joined_at，owner 恒在首位；只读不记审计） |
| DELETE | /projects/{pid}/members/{user_id} | 移除成员（2026-08-17：**仅 owner** get_current_owner_id；移除 owner 本人 4000、自移 4000、目标非成员 4004；审计 project.member_remove 记 target_id；显式 commit） |
| POST | /projects/{pid}/documents | 上传文件（tender/kb） |
| POST | /projects/{pid}/images | 上传章节插图（2026-08-18：jpg/png/gif/webp ≤10MB；仅项目成员；存 MinIO `images/{project_id}/`，返回 {storage_key, url} 签名 URL；审计 image.upload） |
| GET | /projects/{pid}/images/signed | 图片签名读（2026-08-18：query storage_key；仅允许本项目 images 目录下对象，跨项目越权 4003；非成员 403） |
| GET | /projects/{pid}/documents/{did}/format-requirements | 读取格式要求（2026-08-18：项目成员可读；仅 tender_file，其余 doc_type 拒绝 4010；返回 {items:[{category,requirement}]}） |
| PUT | /projects/{pid}/documents/{did}/format-requirements | 更新格式要求（2026-08-18：项目成员可写；body.format_requirements 完整数组幂等覆盖 documents.meta；空 requirement 条目丢弃、未知 category 归 other；仅 tender_file 4010；审计 document.format_requirements_update） |
| GET | /projects/{pid}/documents/{did}/disqualification-clauses | 读取废标条款（阶段 H：项目成员可读；仅 tender_file 4010；返回 {items:[{id,clause_no,title,risk_category,severity,recommendation,confirmed}]}） |
| PUT | /projects/{pid}/documents/{did}/disqualification-clauses | 更新废标条款（阶段 H：body.items 全量删旧插新幂等覆盖；缺 title 丢弃、非法 severity/risk_category 归一；仅 tender_file 4010；审计 document.disqualification_clauses_update） |
| GET | /projects/{pid}/disqualification-clauses | 项目级废标条款汇总（阶段 H：跨文档聚合，供生成页风险横幅） |
| GET | /projects/{pid}/disqualification-risks | 章节废标风险扫描（阶段 H：已确认 high 条款 vs proposal_sections 规则比对，返回 {risks:{章节号:[命中条款]}}） |
| GET | /projects/{pid}/kb/search | 资料库相似度检索（RAG；query 参数 q 必填，top_k∈[1,20] 默认 5，按相似度倒序返回 {items,total}，仅项目成员可调） |
| GET | /projects/{pid}/documents | 文档列表与状态 |
| POST | /projects/{pid}/documents/{did}/reparse | 重新解析招标文件（只提取评分点，不提取技术需求：按 doc_id 删除旧评分点 + 项目级 sp_derived 衍生需求，保留招标原文技术需求 → 状态重置 uploaded → 入队 task_parse_tender（score_points_only=True，LLM schema 裁掉 tech_requirements）；仅 tender_file；parsing/uploaded 状态拒绝 4010；非招标文件 4010；文档不存在 4004；审计 document.reparse） |
| GET | /projects/{pid}/score-points | 评分点列表（可 PUT 单条确认/改 strategy） |
| POST | /projects/{pid}/requirements/generate | 基于已确认评分点梳理技术需求（body.score_point_ids 省略→全部 confirmed 评分点，显式传→勾选梳理；LLM 提炼+sp_id 映射回填；幂等覆盖旧 sp_derived；无评分点 4004；审计 requirements.generate） |
| GET | /projects/{pid}/requirements | 技术需求列表（LEFT JOIN score_points 携带 related_sp；only_mapped=true 仅返回已映射需求） |
| GET | /projects/{pid}/benchmark | 评分对标报告（阶段 D：项目成员可读；confirmed 评分点懒计算 coverage/risk 并回写 risk_level；返回 items[{clause_no,item,score,criteria,strategy,coverage,risk}] 按 score×(1-coverage) 降序） |
| PUT | /projects/{pid}/benchmark/{clause_no}/strategy | 编辑评分点应对策略（阶段 D：**仅 owner**；body.strategy ≤2000 字，空白置 NULL；评分点不存在 4004；审计 benchmark.strategy） |
| POST | /projects/{pid}/generate | 触发方案生成（返回 task_id） |
| POST | /projects/{pid}/workflow/start | 启动方案生成工作流（API 进程后台任务推进，遇 HITL interrupt 停下；在途重复启动被拒 4009） |
| GET | /projects/{pid}/workflow/status | 工作流状态（phase/progress/interrupt/score_points/outline/chapters/error） |
| POST | /projects/{pid}/workflow/confirm-score-points | 确认评分点，resume 工作流进入大纲阶段（前置校验 interrupt 类型） |
| POST | /projects/{pid}/workflow/confirm-outline | 确认大纲（**仅 owner**，2026-08-20 收紧，非 owner 403；2026-08-16 二次编辑增强：body.outline 为前端编辑后大纲、body.mounted_doc_ids 为资料库挂载配置，两者均经 **resume payload** 传给 confirm_outline 节点——不再走 update_state 写 state，避免清除 checkpoint pending interrupt；缺省不携带时保持原大纲/项目全量检索；2026-08-18：增 body.mounted_kb_ids 知识库级挂载，与 mounted_doc_ids 并集生效），节点内替换 state.outline 并落库 proposal_skeletons，resume 进入章节生成 |
| POST | /projects/{pid}/workflow/regenerate-outline | 重新生成大纲（仅 confirm_outline interrupt 挂起时允许；resume 节点 action=regenerate 返回图边标记，经 confirm_outline → generate_outline → confirm_outline 回边重新生成（节点返回值写入 checkpoint，state 与 DB 落库一致），随后再次 interrupt 挂起，保留 pending interrupt） |
| PUT | /projects/{pid}/workflow/outline-draft | 保存大纲二次编辑草稿（**仅 owner**，2026-08-20 收紧，非 owner 403；body.outline 编辑后大纲、body.mounted_doc_ids 挂载配置；upsert proposal_skeletons.draft/draft_updated_at；审计 workflow.outline_draft_save） |
| GET | /projects/{pid}/workflow/outline-draft | 读取草稿（项目成员可读；返回 {outline, mounted_doc_ids, updated_at}，无草稿返回 404；前端进入编辑态拉取，有草稿弹恢复弹窗） |
| DELETE | /projects/{pid}/workflow/outline-draft | 清除草稿（**仅 owner**，2026-08-20 收紧；幂等，draft=NULL；审计 workflow.outline_draft_clear；confirm_outline 确认成功后节点自动调用） |
| POST | /projects/{pid}/workflow/confirm-review | 审阅确认：approved → 导出；feedback → 意见回派 + 章节重写后复审（2026-08-18：feedback 键 chapter_no/标题命中分工 → assignment 置 rejected + 意见落库 + 推送 task_reviewed 并从 feedback 移除；无分工章节保持 rewrite 链路；全部回派后 action=redispatched 重新 interrupt 等待复审，响应 next_phase=redispatch） |
| POST | /projects/{pid}/workflow/rewrite-chapter | 按审阅意见重写指定章节（query 参数 chapter_no、comment） |
| GET | /projects/{pid}/workflow/export | 导出 Word（返回导出状态与存储 key；阶段 H 门禁：存在未确认 high 废标条款时 4012 阻塞，见 §3.12） |
| PUT | /projects/{pid}/workflow/sections/{chapter_no} | 章节人工编辑保存（2026-08-17：body.content；章节不存在于 state chapters 返回 4004；update_state 回写 chapters/chapter_summaries（摘要重算保章间上下文链路）+ proposal_sections upsert（content_md/status=review/updated_at，对齐 write_node 的 _upsert_section 口径）；仅项目成员；审计 workflow.section_edit） |
| POST | /projects/{pid}/workflow/outline-suggest | 大纲优化建议（2026-08-17：仅 confirm_outline 挂起时可用；mock 模式确定性规则建议（覆盖矩阵缺口→add_section/add_chapter），生产模式 LLM schema 建议（外发前 redact，失败降级规则建议）；建议为瞬态数据不落库） |
| POST | /projects/{pid}/workflow/outline-suggest/apply | 应用大纲建议（2026-08-17：body.adopted 为 suggestion_id 列表；纯函数应用返回调整后大纲供人工核对，不写 state——最终执行仍由 confirm-outline 人工确认） |
| POST | /projects/{pid}/workflow/section-suggest | 内容改进建议（2026-08-17：body.chapter_no 可选；mock 规则建议/生产 LLM schema（redact，失败降级空列表）；采纳执行复用 rewrite-chapter） |
| GET | /projects/{pid}/skeleton | 方案骨架 |
| GET | /projects/{pid}/sections | 章节列表（含状态/内容） |
| PUT | /projects/{pid}/sections/{sid} | 章节编辑（人工直接改） |
| POST | /projects/{pid}/sections/{sid}/review | 审阅动作（approve/rewrite+意见） |
| POST | /projects/{pid}/export | 导出 Word（返回下载 URL） |
| GET | /tasks/{tid} | 任务进度轮询 |
| GET | /users | 用户列表（三期：**仅管理员** role=admin 或白名单；查询参数 keyword（邮箱/姓名 ilike）/role 枚举过滤/page；返回 email/display_name/role/created_at，不含 password_hash） |
| PUT | /users/{user_id}/role | 角色变更（三期：**仅管理员**；role ∈ member/kb_admin/admin；不可变更自己 4000；降级 admin 时至少保留 1 名 admin 4000；审计 user.role_change 记 from/to） |
| GET | /rbac/permissions | 权限点目录（阶段 A：**仅 system:manage**；返回 items[{code,name,category}]，供权限矩阵列头） |
| GET | /rbac/roles/{role}/permissions | 角色权限点映射（阶段 A：**仅 system:manage**；role ∈ member/kb_admin/admin，非法角色 422；返回 {role,codes}） |
| PUT | /rbac/roles/{role}/permissions | 全量覆盖角色权限点（阶段 A：**仅 system:manage**；body {codes}，非法/不可授予码（含 project:member_manage）422；admin 角色必须保留 system:manage 防自我锁死 4000；delete+insert 后失效 RBAC 缓存；审计 rbac.update 记 from/to） |
| GET | /audit-logs | 审计日志查询（三期：**仅管理员**，只读；过滤 action 前缀匹配/user_id/project_id/target_type 精确/时间范围 start-end；created_at 倒序分页，LEFT JOIN users 返回 user_name；查询自身记审计 audit.query） |
| GET | /projects/{pid}/chapter-assignments | 分工列表（2026-08-18：项目成员可见；LEFT JOIN users 返回 assignee_name 与 submitted_by_name（提交人标注，审阅页展示），并附章节内容状态 section_status、四个阶段时间戳；2026-08-20：**树形返回**，章行附 children（子节分工）与聚合 approved_count/total；非成员 403） |
| POST | /projects/{pid}/chapter-assignments | 分配章节（2026-08-18：**仅 owner**；body `[{chapter_no,title,assignee_id}]` 批量幂等 upsert；assignee 非项目成员 4004；2026-08-20：chapter_no 支持 `1.1` 子节粒度，**章级分配自动展开为其全部子节批量分配**；推送 WS task_assigned；审计 division.assign） |
| POST | /projects/{pid}/chapter-assignments/{id}/accept | 领取章节（2026-08-18：仅 assignee；pending/rejected → in_progress 并记 accepted_at；非 assignee 403） |
| POST | /projects/{pid}/chapter-assignments/{id}/generate | 生成章节初稿（2026-08-18：仅 assignee；复用 chapter_service.generate_chapter 的 RAG/脱敏/mock 链路，回写 state.chapters + proposal_sections（status=draft）；章节不在大纲 4004） |
| POST | /projects/{pid}/chapter-assignments/{id}/submit | 提交待审（2026-08-18：仅 assignee；in_progress → submitted 并记 submitted_at；推送 WS task_submitted） |
| POST | /projects/{pid}/chapter-assignments/{id}/review | 审核（2026-08-18：**仅 owner**；body `{action: approved\|rejected, comment}`；approved → approved（并检查自动版本快照，见 §3.10），rejected → rejected 附意见可重新领取重编；推送 WS task_reviewed；审计 division.review） |
| POST | /projects/{pid}/chapter-assignments/{id}/assist-generate | AI 辅助生成（2026-08-18：仅 assignee 且状态 in_progress/rejected；body `{prompt, mode: append\|overwrite}`；检索范围 = 项目挂载 ∪ 本人个人库，上下文 = 前文摘要 + 评分点 + 技术需求 + prompt；流式经 WS section_token（source=assist）；落库双写；同章已有任务 4000；审计 division.assist_generate） |
| POST | /projects/{pid}/chapter-assignments/{id}/assist-generate/stop | 暂停辅助生成（2026-08-18：仅 assignee；置位取消令牌，生成端点保留已生成部分按 mode 落库；无进行中任务返 stopped=false） |
| GET | /projects/{pid}/chapter-assignments/{id}/annotations | 章节批注列表（2026-08-18：项目成员可读；按时间正序，附批注人姓名） |
| POST | /projects/{pid}/chapter-assignments/{id}/annotations | 新增批注（2026-08-18：assignee/owner 可写，其余成员 403；body.content 非空；审计 division.annotate） |
| GET | /projects/{pid}/chapters/{chapter_no}/annotations | 章节批注列表（阶段 E5：项目成员可读，按 created_at 正序，附作者姓名/updated_at） |
| POST | /projects/{pid}/chapters/{chapter_no}/annotations | 新增章节批注（阶段 E5：项目成员 + check_chapter_editable 口径可写，否则 403；content 1-2000；审计 annotation.create） |
| PUT | /projects/{pid}/chapters/{chapter_no}/annotations/{annotation_id} | 编辑批注（阶段 E5：写权限校验后仅批注作者或项目 owner 可改，否则 403；审计 annotation.update） |
| DELETE | /projects/{pid}/chapters/{chapter_no}/annotations/{annotation_id} | 删除批注（阶段 E5：同 PUT 权限口径；审计 annotation.delete） |
| GET | /projects/{pid}/versions | 版本列表（2026-08-18：项目成员可读；version 倒序；created_by NULL = 自动快照标记 auto=true） |
| POST | /projects/{pid}/versions | 手动版本快照（2026-08-18：**仅 owner**；body.snapshot_note 可选；Word + Markdown 源入 MinIO，version 续号；无章节内容 4000；审计 version.snapshot） |
| GET | /projects/{pid}/versions/{id}/download | 版本下载（2026-08-18：项目成员；query type=docx\|source 二选一，返签名 URL） |
| POST | /projects/{pid}/versions/{id}/archive | 归档公司知识库（2026-08-18：**仅 owner**；body.kb_id 限公司级库否则 400；登记全局素材（project_id=NULL）+ 入队分块向量化；审计 proposal.archive） |
| POST | /projects/{pid}/versions/{id}/rollback | 版本回滚（阶段 E5：**仅 owner**；按 snapshot_json 回写章级 proposal_sections（status=draft）并同步图状态，返回 chapters_restored；无结构化快照 400；审计 version.rollback） |
| GET | /workbench/summary | 工作台汇总（2026-08-20：登录即可；单端点返回双视图数据——我的任务分桶（待领取/编制中/被打回/已提审/已通过，含项目名与章节号）、我的参与项目进度（total/approved/percent/状态分布 + phase 附注）；owner 额外返回 owner_review_pending 待审核清单，非 owner 返空） |

**前端 HITL 交互契约**（2026-08-16 补）：所有 confirm 端点均校验 pending interrupt，前端不得直接调用，须先确保工作流停在对应 interrupt：
- 招标解析页（ParseView 内嵌 ParseConfirmView）：「确认并生成大纲」先 GET workflow/status，无挂起 interrupt 则 POST workflow/start，轮询（1s×60）直到 interrupt.type=confirm_score_points 再调 confirm-score-points；state.error 非空时展示解析失败原因。**短路引导（2026-08-16）**：status 已挂起其他类型 interrupt（大纲确认/章节审阅）或 phase 已推进到 outline 之后（generate/review/done）时，不重复 start（在途重复启动被后端 4009 拒绝）也不盲等，立即提示「工作流已进入后续阶段，请前往方案生成页继续操作」；phase=confirm 无 interrupt 时（parse 节点刚完成、interrupt 即将挂起）仅轮询等待不 start。页面存在 uploaded/parsing 状态招标文件时每 5s 自动轮询解析状态。
- 方案生成页（GenerateView）按 workflow/status 三态呈现：① phase=init 或停在 confirm_score_points → 引导回招标解析页；② 已启动但 outline 为空 → 大纲后台生成中，每 2s 轮询 status（上限 4 分钟）；③ interrupt=confirm_outline → 展示大纲（每章标注覆盖评分点条款号 covered_clauses）、资料库挂载配置与「大纲编辑」卡片（**树形编辑**：递归树形结构，章节编号 1/1.1/1.1.1 按位置自动重算，支持增删子节/上下移/升降级（≤4 层）/改标题与覆盖评分点；**左侧大纲树** a-tree 与编辑区实时同步，生成态展示大纲章节+子节），**草稿保存**（防抖 2s 自动 PUT outline-draft + 手动保存 + 刷新后 GET 拉取弹恢复弹窗，confirm-outline 确认成功后自动清除），操作按钮：「重新生成大纲」（popconfirm 确认后调 regenerate-outline，完成后自动刷新）与「确认并生成」（primary，即 confirm-outline，携带编辑后 outline + mounted_doc_ids；前端先校验至少 1 章且标题非空）。章节生成期间除 WS 流式事件外，每 3s 轮询 status 兜底（progress≥0.75 或 phase=review/done 视为完成，防 WS done 事件丢失后页面永久停留在生成中）。前端失败提示透出后端 BizError message。章节卡片支持预览/编辑切换（a-segmented + textarea，生成中禁用），编辑态「保存」调 PUT workflow/sections/{chapter_no} 直接落库（成功刷新章节内容、重置草稿）；大纲确认态新增「AI 优化建议」卡片（获取建议 → 勾选 → 应用建议 → 返回调整后大纲重建编辑树并提示「已生成调整后大纲，请核对后确认」，最终仍走 confirm-outline 人工确认）；内容阶段章节卡片新增「AI 改进建议」（对当前章或全部已生成章，每条「采纳重写」popconfirm 确认后复用 rewrite-chapter）；无建议时展示「未发现可优化项」。

### 5.2 WebSocket

- `/ws/{project_id}?token=<JWT access token>`：握手阶段鉴权（token 无效 close `4001` / 非项目成员 close `4003`，refresh token 拒绝）；连接建立后转发节点经 Redis 频道 `bid:events:{project_id}` 发布的工作流进度与章节事件，并支持客户端 `ping/pong` 心跳与 `get_status`（读取 checkpointer 实时状态）。
- `/ws/user/{user_id}?token=<JWT access token>`（阶段 C）：握手仅校验 token（sub 必须等于 user_id，订阅他人频道 close `4003`，无项目成员校验）；转发 Redis 频道 `bid:user:{user_id}` 的用户级事件（task_assigned/task_submitted/task_reviewed/workbench_refresh），支持 `ping/pong` 心跳；分工端点与 confirm-outline 经 `publish_user_event` 定向发布，前端 WorkbenchView 收事件静默刷新待办。

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
graph.add_node("retrieve", retrieve_node)      # RAG 检索当前章节素材（召回+rerank 精排）
graph.add_node("write", write_node)            # 撰写章节（三期：真流式，on_delta 节流发 section_token）
graph.add_node("validate", validate_node)      # 校验章节
graph.add_node("consistency_check", consistency_check_node)  # 全文一致性检查（integrate 前）
graph.add_node("integrate", integrate_node)    # 术语/编号/目录整合
graph.add_node("review", review_node)          # HITL：interrupt() 等人工
graph.add_node("rewrite", rewrite_node)        # 按反馈局部重写
graph.add_node("export", export_node)          # 导出 Word

graph.add_edge("parse", "skeleton")
graph.add_edge("skeleton", "retrieve")
graph.add_conditional_edges("validate", chapter_route, {"write": "write", "retrieve": "retrieve", "consistency_check": "consistency_check", "integrate": "integrate"})
graph.add_edge("consistency_check", "integrate")
graph.add_edge("integrate", "review")
graph.add_conditional_edges("review", review_route, {"approved": "export", "feedback": "rewrite"})
graph.add_edge("rewrite", "integrate")
graph.add_edge("export", END)

# 章节循环：skeleton 后对每个 section 执行 retrieve→write→validate；
# 全部完成后先经 consistency_check 再 integrate（错误路径直达 integrate）
```

**全文生成质量保障**（阶段三）：

1. **章节间上下文注入**：每章生成后提取 ≤200 字摘要存 `state.chapter_summaries`（去 Markdown 标记截断，`extract_chapter_summary`），`write_node` 按大纲顺序将已完成章节摘要注入下一章提示词（`chapter.yaml` 新增全文一致性约束：术语统一/编号连续/不得复述/衔接自然）；rewrite 后同步刷新摘要。
2. **评分点覆盖矩阵**：`coverage_service.compute_coverage` 比对 confirmed 评分点与大纲 `covered_clauses`；未覆盖评分点注入各章提示词补写（supplement_points），`coverage_rate` 随 progress 事件推送前端。
3. **全文一致性检查**：`consistency_check_node`（integrate 前）经 `consistency_service.check_consistency` 一次 LLM 调用检查术语冲突/重复段落/编号断裂；可修复 issues 按章聚合意见走一轮定向重写（复用 rewrite 链路，最多 1 次，落库+section_done 事件）；不可修复/已重写过/检查异常 → warning 事件降级，不阻塞导出；mock 模式直通空 issues（E2E 确定性）。
4. **质量增强三件套（阶段 E）**：① **参数比对校验**（E1）——validate_node 接入 `param_check_service.check_chapter_params`（★条款正则断言抽取 + 正文数值比对，万/亿归一化，LLM 兜底，mock/异常降级 pass），issues 并入校验失败走 write 重试；② **术语表**（E2）——招标文件解析 schema 提取 `glossary: [{term, canonical, desc}]` 存 documents.meta 并注入 state.glossary，integrate 节点 unify_terms 统一术语（mock 直通），chapter.yaml `{glossary}` 段注入章节提示词；③ **引用溯源**（E3）——retrieve_node 采集检索命中 `{doc_title, page_no, chunk_id, score}` 入 state.retrieved_citations，write_node 落库章级 `proposal_sections.citations`，供前端展示与 E4 导出标注。

**大纲节点输出契约（2026-08-16 增强）**：`generate_outline_node` 的 LLM 响应 schema 为 `{"chapters": [{chapter_no, title, sections, covered_clauses}]}`，`covered_clauses` 为本章节关联的评分点条款号数组（必填，可为空数组——前置章节如项目概述无关联条款；骨架章节不得为空），用于评分点覆盖校验与追溯。提示词正文（prompts/outline.yaml，2026-08-16 两次优化）：**核心章节按最终定稿骨架模板组织**（顺序与命名保持，子节由技术需求推导）——①需求分析（按性能/信创/安全/对接/实施交付类别归纳全部技术需求）②业务流程设计（巡检/告警处置/数据流转等）③总体架构设计（架构、选型、信创适配、性能指标支撑）④详细功能说明（功能类需求逐项实现要点）⑤对接方案（外部系统与设备接口/协议/联调）⑥培训与运维服务方案（培训、运维保障、实施交付）；无对应技术需求内容时允许精简合并相关章节，可补充项目概述等前置章节。**技术需求为核心唯一依据填充章节内容**——全部技术需求完整映射无遗漏；**评分点仅作追溯辅助**（covered_clauses 标注），不得以评分项/分值划分章节，不得直接采用评分项名称作为章节标题，无对应技术需求的评分项并入最相关章节；user_prompt 中技术需求优先于评分点呈现。大纲整段（含 covered_clauses）随 `proposal_skeletons.tree` JSONB 持久化，下游 confirm-outline HITL 可读取并编辑。

**大纲二次编辑（2026-08-16）**：`confirm_outline_node` 的 resume payload 支持 `outline`（编辑后大纲：替换 state.outline 并落库 `proposal_skeletons`，DB 与 state 一致，随后进入章节生成）与 `mounted_doc_ids`（挂载配置写入 state）；两者由 API 层直接放入 resume payload 传递，**不经 update_state**（`aupdate_state` 会清除 checkpoint pending tasks，导致 interrupt 丢失后工作流 4009 卡死——2026-08-16 实测缺陷）。

**草稿联动与嵌套 sections**（2026-08-16）：① `confirm_outline` 确认成功后调用 `_clear_outline_draft` 清除 `proposal_skeletons.draft`（防陈旧草稿下次进入编辑态误恢复）；② `retrieve_node`/`generate_chapter` 经 `flatten_sections` 兼容大纲 sections 两种形态——字符串数组（`["背景","政策"]`）与嵌套树（`[{title,children}]`），递归推导编号 1/1.1/1.1.1 并扁平化为子节列表，前端树形编辑（嵌套 children）与后端扁平消费（string[]）解耦；③ 草稿三函数（save/get/clear）实于 `workflow_runtime`，API 三端点（PUT/GET/DELETE outline-draft）含审计埋点，前端防抖 2s 自动保存 + mounted_doc_ids 随草稿一并存取。

**重新生成大纲**：`workflow_runtime.regenerate_outline` 仅允许 confirm_outline interrupt 挂起时调用（先经 ensure_pending_interrupt 校验，否则 4009）；实现为 resume confirm_outline 节点（resume 值 `{"action": "regenerate"}`）返回图边标记 `regenerate_requested`，经 `outline_route` 条件边（confirm_outline → generate_outline → confirm_outline 回边）重新生成并落库 `proposal_skeletons`，**节点返回值正常写入 checkpoint**（state.outline 与 DB 一致），随后再次 interrupt 挂起（保留 pending interrupt，前端可继续确认，支持多次重新生成）；确认（True/confirmed）后清除标记返回进入章节生成。历史缺陷：曾内联调用 generate_outline_node（普通函数返回不经图，checkpoint 仍旧大纲、DB 已新大纲），确认后章节按旧大纲生成——2026-08-16 已改图边路由根治（回归样本验证）。异常经 BizError 5011 透出。

**人工编辑保存与两阶段建议闭环（2026-08-17）**：① 人工编辑保存 `workflow_runtime.save_section_edit`——校验章节存在于 state chapters（否则 4004）→ `update_state` 回写 `chapters`/`chapter_summaries`（`extract_chapter_summary` 摘要重算，保全文一致性链路）→ `proposal_sections` upsert（content_md/status=review/updated_at，对齐 write_node 的 `_upsert_section` 口径）；② 大纲建议 `outline_suggest_service`——`build_outline_suggestions`（mock 模式规则建议：覆盖矩阵缺口→add_section/add_chapter，评分点含 LLM 占位数据时触发确定性兜底建议保证 mock 下 E2E 可断言；生产模式 LLM schema 建议，外发前 redact，失败降级规则建议）+ `apply_outline_suggestions` 纯函数按 suggestion_id 应用（suggestion_id 服务端编码 `{type}:{参数}:{b64(标题)}`，应用幂等去重）；建议为瞬态数据不落库，apply 仅返回调整后大纲供人工核对，最终执行仍由 confirm-outline 人工确认；③ 内容建议 `section_suggest_service`——mock 模式规则建议（未覆盖评分点 → 最相关已生成章节，severity 随星标）/生产模式 LLM schema（redact，失败降级空列表）；采纳执行复用 rewrite-chapter 既有链路（人工确认门禁）。

### 6.2 HITL 与中断恢复

- `review_node` 内调用 `interrupt({section_id, content_md, score_points})`；
- 用户通过 / 编辑 / 重写后 `Command(resume=...)` 恢复执行（resume 前校验 pending interrupt 类型匹配，不匹配拒绝）；
- Checkpointer：`PostgresSaver` 持久化，`thread_id = project_id`，支持任务中断后从断点续跑；
- 资料库挂载（二期）：`confirm-outline` 将 `mounted_doc_ids` 经 resume payload 传给节点写入 state（None=项目全量检索；空列表=明确不挂载），`retrieve_node`/`write_node` 读取并透传 `doc_ids` 给 `retrieve_similar`/`generate_chapter`，限定 RAG 检索范围；
- 长任务：工作流由 API 进程的 asyncio 后台任务推进（不经 Arq worker），Checkpointer 采用 AsyncPostgresSaver + 独立 psycopg 连接池（不与业务 SQLAlchemy 会话混用），由 app lifespan 初始化/释放；Arq worker 仅用于招标文件解析、资料入库等异步任务。前端通过 WebSocket 接收进度与 interrupt 通知。

### 6.3 工具注册

| 工具 | 用途 | 授权 | 落地状态 |
|---|---|---|---|
| kb_search | 资料库检索（embedding 相似度+rerank） | 自动 | 阶段 F 已落地（`app/agents/tools.py`） |
| get_score_points | 读取当前项目评分点 | 自动 | 阶段 F 已落地 |
| list_sections | 读取已生成章节 | 自动 | 阶段 F 已落地（section_id/title/≤200 字摘要） |
| update_glossary | 更新术语表 | 自动 | 阶段 F 已落地（纯函数合并，同名覆盖，经节点返回写回 state.glossary） |
| web_search | 行业公开资料检索 | 二期（需人工授权） | 未实现（不在本轮范围） |

**Tool Calling 链路（阶段 F）**：`llm_service.chat_with_tools`（LiteLLM `tools` 参数 + tool_call 解析循环 ≤3 轮，工具结果 redact 脱敏后回填续问，工具异常回填「工具执行失败」不中断，轮数耗尽不带 tools 强收敛；mock 模式直通纯文本分支不触发任何工具）；工具注册表 `app/agents/tools.py`（TOOL_SCHEMAS + `execute_tool` 按名调度，kb_search 含 mock 确定性桩分支）。**节点接入（保守，图拓扑不动）**：write_node 生成前真实模式下经 `write_tool_preflight` 绑定 kb_search/get_score_points 由 LLM 自主决定补充检索（命中素材追加到 retrieve 基础上下文，异常降级原上下文）；validate_node 存在 issues 时经 `validate_tool_recheck` 绑定 list_sections/get_score_points 取证复核（输出 `{"keep": [...]}` 过滤误报，解析失败保守保留全部）。mock 模式行为与现版本逐字节等价（tool 分支不触发）。

### 6.4 提示词体系（MVP 五件套）

| 提示词 | 输入 | 输出 | 关键约束 |
|---|---|---|---|
| 招标解析器 | 评标办法原文 | JSON（评分点/资格/需求/格式要求/术语表/废标条款） | JSON Schema、禁止臆测分值；阶段 H：第 4 类废标/红线条款提取（risk_category/severity 枚举约束，明确废标后果为 high） |
| 骨架规划器 | 技术需求（核心）+评分点（追溯） | 章节树 JSON | 定稿骨架模版（2026-08-16 广东施组定稿）：需求分析/业务流程设计/总体架构设计/详细功能说明/对接方案/培训与运维服务方案 六章，顺序命名保持；技术需求全映射无遗漏；评分点经 covered_clauses 追溯、禁止评分项名称作章节标题 |
| 章节撰写器 | 章节计划+检索素材+前文摘要+高风险对标要点（阶段 D：`{benchmark_high_risk}` 段，高风险评分点「- 条款号: 策略」行，脱敏后外发，缺省回退「（无）」）+术语表（阶段 E2：`{glossary}` 段，term/canonical/desc 行，缺省回退「（无）」） | Markdown 正文 | 只用检索素材、参数不低于★要求；术语按术语表规范表述；「详细功能说明」类章节按模块固定结构撰写（系统概述→需求设计→功能架构→核心功能点[功能说明/界面设计/业务流程设计]）；高风险评分点须针对性正面响应 |
| 校验器 | 正文+评分要求 | pass/fail+issues | 必答要点/字数/参数检查（阶段 E1：param_check_service 正则断言抽取+万/亿归一化规则比对，不确定时 LLM 兜底判定，mock/异常降级 pass）；阶段 H：废标条款拦截（已确认 high 条款分类关键词/标题前缀命中正文即追加废标风险 issue，异常降级放行） |
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
- Reranker 已引入（云端 API，见 7.2 降级矩阵）；离线评测框架已落地（见 §10.3，含合成种子样本；真实标注样本由业务人员后续补充），人工确认页继续作为运行时兜底。

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
- RBAC 权限点体系（2026-08-17 落地，迁移 0011_rbac）：`roles`/`permissions`/`role_permissions` 三表 + 幂等种子（member/kb_admin/admin 三角色）；6 权限点收敛（system:manage/kb:manage/kb:read/kb:upload/settings:read 落角色表；project:member_manage 为 owner 数据属性不落表）；`require_permission(code)` 依赖以 `users.role` → `role_permissions` 判定（模块级缓存，PUT /users/{id}/role 后失效重载），`BID_ADMIN_USER_IDS` 白名单命中恒放行；现有管理端点行为等价收敛（deps `_is_admin`/`_is_kb_admin` 改基于权限点）；**权限点可配置（阶段 A，2026-08-20）**：GET/PUT /rbac/roles/{role}/permissions 读写角色映射（仅 system:manage，审计 rbac.update，admin 保留 system:manage 防自我锁死，project:member_manage 不可授予），/auth/me 返回 permissions 数组，前端菜单/路由改权限点驱动（hasPerm），用户管理页新增「角色权限」矩阵 Tab；后端 403 兜底；
- 章节级编辑权限「可视不可改」（2026-08-18，2026-08-20 子节下沉与收紧）：项目成员可读全部章节；已分配章节/子节仅 assignee/owner 可编辑（`check_chapter_editable` 最小粒度匹配：子节分工优先，章级分工覆盖其下子节），PUT workflow/sections/{chapter_no} 保存前校验，越权 403；**无任何分工的章节仅 owner 可编辑**（行为收紧）；分工分配/审核仅 owner，领取/生成/提交仅 assignee，后端 403 兜底；
- **按钮权限矩阵（2026-08-20，前端隐藏 + 后端 403 双保险）**：前端 `usePermission()` composable 统一判定（当前用户角色 + 项目 owner/assignee），各页面按钮按其渲染：

| 操作 | owner | assignee | 普通成员 | kb_admin/admin 附加 |
|---|:-:|:-:|:-:|:-:|
| 确认大纲/二次编辑（outline-draft/confirm-outline） | ✅ | — | — | — |
| 分配/审核/打回（chapter-assignments） | ✅ | — | — | — |
| 领取/编制/提审（accept/generate/submit） | ✅ | ✅ | — | — |
| 查看目录/正文 | ✅ | ✅ | ✅ | — |
| 建公司库/删全局素材 | — | — | — | ✅ |
| 模型设置（settings/llm 写） | — | — | — | admin |
- 知识库分级权限（2026-08-18）：可见性矩阵 company 全员/project 限成员/personal 仅本人（`kb_base_service.visible_bases`）；建库 personal 任意登录用户/project 仅该项目 owner/company 仅 kb_admin/admin；删库限创建者（company 库限管理员）；素材上传 kb_id 归属校验库可写；辅助生成/初稿生成的检索范围限定项目挂载 ∪ 本人个人库，不越权读取他人个人库；图片签名读限本项目 `images/{project_id}/` 前缀（跨项目 4003）；批注仅 assignee/owner 可写；版本快照/归档仅 owner（归档目标库限公司级），均落审计（kb.base_*/division.assist_generate/division.annotate/image.upload/version.snapshot/proposal.archive）；
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

可量化三项（提取准召率/覆盖/检索）由离线评测框架度量，执行方式：`cd backend && python -m eval.run --task all`（或 `make eval`），`--check` 用于门禁（未达标退出码非零，skipped 不计失败）。

### 10.3 评测框架（离线质量度量）

代码位于 `backend/eval/`（独立于 app 分层，仅复用 services 层函数）；单测一律 mock，禁止真实 LLM/Embedding 调用；缺 Key（非 mock 模式）时对应任务自动 skipped 并在报告注明。

**数据集 schema**（`eval/datasets/{extraction,coverage,retrieval}/*.json`，含合成种子样本）：

| 类型 | 结构 |
|---|---|
| extraction | `{id, name, tender_text, gold: {score_points: [{clause_no, item, criteria, is_star}], tech_requirements: [{seq, description, category}]}}` |
| coverage | `{id, score_points: [{clause_no, item, confirmed}], outline: [{chapter_no, title, covered_clauses}]}`（格式同工作流 state） |
| retrieval | `{id, docs: [{doc_id, title, chunks}], queries: [{query, relevant_doc_ids}]}` |

**三项任务与指标口径**：

| 任务 | 链路 | 指标 | 默认阈值 |
|---|---|---|---|
| extraction | `parse_service.parse_tender_with_llm` 提取 → 与 gold 匹配（clause_no 精确优先，item 字符 bigram F1 ≥0.5 兜底；重复预测只计一次） | precision / recall / F1 | F1 ≥ 0.85 |
| coverage | `coverage_service.compute_coverage`（未确认评分点不计入），多样本取均值 | coverage_rate | ≥ 0.90 |
| retrieval | 数据集离线灌库 kb_chunks → `rag_service.retrieve_with_rerank` → doc 首现序（rerank 未启用时报告注明为纯向量召回序） | Recall@8 / MRR 均值 | Recall@8 ≥ 0.80（框架保守设定） |

出稿时间（≤4h）与 Word 可编辑性依赖真实运行，不纳入自动化评测。

### 10.4 冒烟用例（开发自测）

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
- reviews 表已有完整记录 → 扩展版本表与 diff（2026-08-18：proposal_versions 版本库已落地，见 §3.10；尚缺版本间 diff/回滚）；
- 知识库容器 knowledge_bases → 扩展库级配额/素材移动/跨库引用统计，当前仅容器 + 可见性开关，不改变分块/向量链路（2026-08-18 已落地，见 §3.2）；
- 权限模型 project_members → 扩展项目内角色细分（当前 RBAC 仅覆盖全局功能权限，项目内为 owner/协作者两级 + 章节级 assignee 编辑权限（2026-08-18 已落地，见 §3.9/§九），尚不支持多负责人/章节内段落级协作）；
- 格式要求 `documents.meta.format_requirements` → 扩展为公司模板库（多套排版预设 + 模板文件管理），当前仅支持单项目招标文件驱动；
- 分工协作 chapter_assignments → 扩展截止日期/工作量统计/章节依赖编排，当前仅状态机跟踪。

### 11.3 待确认项

1. 公司标书模板样式（封面/页眉页脚/字号规范）需售前团队提供；
2. 首批入库资料清单（3 份产品手册 + 2 份历史方案）；
3. LLM 供应商账号与预算（DeepSeek 主用 + Qwen 备用）；
4. 服务器资源申请（8C16G × 2）。
