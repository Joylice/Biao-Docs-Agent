# 0001-架构分层治理（api → services → agents）

- 状态：已接受
- 日期：2026-08-31
- 决策人：技术管理部 / 架构组
- 关联：[overview.md](../overview.md)（Phase1-5 交付明细）、[SDD.md](../SDD.md) §2.1、AGENTS.md「分层铁律」

## 背景

系统早期存在三层耦合：API 层直连 LLM（`division.py` 内 `call_llm_text`）、agents 层直接操作 ORM、`workflow_runtime.py` 膨胀至 755 行（上帝模块）。后果：跨层绕过难以测试、单测需 mock 过多、模块边界模糊导致回归风险随迭代线性上升。

## 决策

确立唯一依赖方向并强制执行：

```
api → services → agents / models
```

1. **api 层**：只做 HTTP 契约（路由/参数校验/响应），不直连 DB、不直调 LLM。
2. **services 层**：业务逻辑与领域服务（document / llm / project / proposal / infra 五域），持有 DB 与 LLM 访问权。
3. **agents 层**：仅 LangGraph 编排，DB 操作一律经 service 层注入（见 Phase4：`_shared.py` 的 3 个 ORM 操作迁入 `workflow_metadata_service` + `chapter_service`）。
4. **models**：SQLAlchemy 模型只定义映射，不承载业务逻辑。

配套动作：
- 公共工具下沉 `app/core/sorting.py`（natural_sort_key / numbered_sections），消除跨域伪耦合。
- 上帝模块拆分：`workflow_runtime.py` 755 行 → 4 文件（344+274+75+93），re-export 保持 API 兼容。
- 前端同步治理：composable 拆分（`useChapterLoader`/`useChapterSave`/`useAssistSelection`/`useAssistChapter`/`useTaskWorkflow`）、Toolbar 按 Ribbon 选项卡拆 4 子组件、`ReviewView` 编排抽 composable。

## 备选方案

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| 维持现状（api 直连） | 零成本 | 测试难、耦合高、无法并行开发 | 否决 |
| 全量 DDD 分层 | 理论最规范 | 对中小团队过度设计，周期长 | 否决 |
| 三层治理（选定） | 成本可控、边界清晰、可增量推进 | 需人工守护分层铁律 | 已接受 |

## 后果

- 正面：API 层薄化后可独立测路由；agents 可注入 service 测试编排；关键模块覆盖率门禁（≥80%）可路径化执行。
- 负面：Phase 拆分期间存在中等重构风险（Phase3/4 标注「高」），依赖 CI 覆盖兜底。
- 迁移路径：后续新功能一律按三层落位，CI 中增加分层合规检查（开发规范 §3.2 验证命令）。

## 验证

- `make check`（lint + format + mypy strict + pytest 覆盖率 ≥70%）。
- 关键模块覆盖门禁 `make test-coverage-gates`（parse/rag/export/redact/graph ≥80%）。
- E2E 全链路回归（Playwright 16 spec）通过。

## 变更记录

- 2026-08-31：Phase1-5 全部交付，ADR 落档。
