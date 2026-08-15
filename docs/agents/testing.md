# testing.md — TDD 与 E2E 规约

> AGENTS.md 分域规约。强制 TDD：先写失败测试再实现；覆盖率不达标 = CI 失败 = 禁止合并。

---

## 1. TDD 开发循环（红-绿-重构）

```
① 红   写失败测试（断言行为契约，不实现）
② 绿   最小实现通过测试
③ 重构 清理实现，测试保持绿
```

- **禁止**"先实现后补测试"；功能 PR 无对应测试 = 不合规，评审直接打回；
- 测试失败时先诊断（读报错/日志），禁止"改测试迁就实现"掩盖问题。

## 2. 测试分层与目录（镜像 app/）

| 层 | 目录 | 覆盖对象 | 工具 |
|---|---|---|---|
| 单元 | `backend/tests/unit/` | 分块、脱敏、校验器、风险分级、提示词解析 | pytest |
| 服务 | `backend/tests/services/` | parse/rag/export/generate 各 service | pytest + monkeypatch |
| 接口 | `backend/tests/api/` | REST/WS 契约、权限隔离、错误码 | pytest + httpx TestClient |
| Agent | `backend/tests/agents/` | LangGraph 全链路 + interrupt 恢复 | pytest + fixture 项目 |
| E2E | `e2e/` | 浏览器全链路（见 §4） | Playwright |

## 3. 覆盖率门槛（路径化，CI 强制执行）

### 3.1 全仓门槛（pyproject.toml 中固化）

```toml
[tool.coverage.run]
source = ["app"]
omit = ["app/main.py", "app/core/config.py"]

[tool.coverage.report]
fail_under = 70        # 全仓 ≥ 70%
skip_covered = true
```

### 3.2 关键模块门槛（独立命令，单独 gate）

```bash
# 关键模块 ≥ 80%，CI 逐个执行，任一不达标即失败
pytest backend/tests/services --cov=app.services.parse_service  --cov-fail-under=80 -q
pytest backend/tests/services --cov=app.services.rag_service    --cov-fail-under=80 -q
pytest backend/tests/services --cov=app.services.export_service --cov-fail-under=80 -q
pytest backend/tests/unit    --cov=app.core.redact             --cov-fail-under=80 -q
pytest backend/tests/agents  --cov=app.agents.graph            --cov-fail-under=80 -q
```

### 3.3 测试规约

- 命名 `test_<函数>_<场景>_<预期>`（如 `test_extract_score_points_star_clause_ok`）；
- DB 测试用 fixture 建临时 schema，禁止污染共享库；
- **LLM 一律 mock**（`tests/fixtures/llm_mock.py`），禁止测试中真实调用模型；
- 提示词回归样本 `tests/fixtures/prompt_cases.json`（评分点 → 期望输出），提示词改动必须跑通：
  ```bash
  pytest backend/tests/unit -k prompt -q
  ```

## 4. E2E（全链路回归，合并 main 前必跑）

### 4.1 Playwright 场景清单

| # | 场景 | 关键断言 |
|---|---|---|
| E2E-01 | 注册 → 登录 → 创建项目 | 进入工作台，项目可见 |
| E2E-02 | 上传招标文件 → 解析 → 确认 | 评分点表格展示，确认后状态 parsed |
| E2E-03 | 上传 3 份资料 → 检索命中 | 生成页素材引用出现资料标题 |
| E2E-04 | 触发生成 → 流式输出 → 完成 | 章节逐段渲染，全部章节完成 |
| E2E-05 | 审阅：反馈重写一章 | 该章内容更新，其余章不变 |
| E2E-06 | 导出 Word → 下载校验 | 下载成功，文档含目录与正文 |
| E2E-07 | 越权访问他人项目 | 返回 403，数据不泄露 |

### 4.2 运行要求

- E2E 依赖 `docker compose up` 全栈 + fixture 数据（`e2e/fixtures/`：样例招标 PDF、样例产品手册）；
- 涉及前端交互/API 契约的改动必须补/改对应场景；新增业务流程必须新增场景；
- 禁止"人工点一遍就算"。

```bash
cd e2e && npx playwright test        # 全量
npx playwright test -g "E2E-04"      # 单场景
```

## 5. 验收口径（对齐 MVP 目标）

| 指标 | 目标 | 对应测试 |
|---|---|---|
| 评分点提取准召率 | ≥ 85% | 单测 + prompt_cases 回归 |
| 方案评分点覆盖 | ≥ 90% | Agent 集成测试 |
| 单项目出稿 | ≤ 4h | E2E-04（时长标记） |
| 输出 Word 可编辑 | 目录/页码/样式规范 | E2E-06 |
| 中断恢复 | 断点续跑成功 | Agent 集成测试 |
