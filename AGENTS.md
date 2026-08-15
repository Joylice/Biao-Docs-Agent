# AGENTS.md — 投标软件技术方案智能体

> 本文件由 **AI 编码代理与开发者共同遵守**，置于仓库根目录以便 Claude Code / Cursor / Codex 等 harness 自动加载。
> 根文件只放**最高优先级约束与文件地图**；详细规约按域拆分在 `docs/agents/`，按需读取，避免占用上下文预算。
> 冲突时以本文件为最高优先级；本文件与设计文档冲突时，同步修订设计文档。

---

## 项目一句话

投标软件技术方案智能体：输入招标文件（PDF/Word）+ 公司资料库，输出符合招标评分标准的**可编辑 Word 技术方案初稿**与评分点对标报告。MVP = P0 核心闭环（招标解析 → 评分对标 → 骨架生成 → 章节生成 → Word 导出）+ P1（真实资料 RAG、章节级审阅重写、流式输出）。

技术栈（锁定，勿擅自替换）：Vue3+TS / Python3.12+FastAPI / LangGraph+PostgresSaver / pgvector / MinIO / Redis+Arq / LiteLLM（DeepSeek-V3 主、Qwen-Plus 备）/ bge-m3。

## 最高优先级铁律（违反 = 评审直接打回）

1. **分层铁律**：依赖方向 `api → services → agents/models`，禁止跨层绕过（api 不得直连 DB/LLM）。验证命令见 `docs/agents/development.md §3.2`。
2. **强制 TDD**：先写失败测试再实现；全仓覆盖率 ≥ 70%，关键模块 ≥ 80%，不达标即 CI 失败。见 `docs/agents/testing.md §3`。
3. **安全门禁**：外发 LLM 必须先脱敏；依赖扫描无高危未豁免项；项目级越权用例必过。见 `docs/agents/security.md`。
4. **先读后改**：动任何代码前，先读「相关设计文档索引 + 目标文件 + 其现有测试」；禁止基于假设动手。
5. **文档同步**：改 API → 同步 SDD §5；改 DB → 生成迁移 + 同步 SDD §4；改 LangGraph → 同步 SDD §6；改提示词 → 跑通回归样本。

## 文件地图（按需读取，勿一次性全读）

| 文件 | 内容 | 何时读 |
|---|---|---|
| `docs/agents/development.md` | 命名/Git/风格、代码设计原则（SOLID·耦合内聚）、架构约束、DB 流程、API 规约、LangGraph 规约、错误处理、脱敏（**含验证命令**） | 任何编码改动前 |
| `docs/agents/testing.md` | TDD 循环、测试分层、覆盖率门槛（路径化命令）、E2E 场景 | 写/改测试、提 PR 前 |
| `docs/agents/security.md` | 依赖扫描、脱敏、越权用例、审计日志、发布自检清单 | 提 PR、发布前 |
| `docs/方案书.md` | 需求与整体方案（决策依据） | 需求理解 |
| `docs/SDD.md` | 模块/DB/接口/编排设计（**唯一权威**） | 设计查询 |
| `docs/MVP.md` | 范围边界与 P0/P1/P2 分层 | 范围判断 |

## 默认工作流（接到任务按此执行，不要跳步）

```
① 读    命中文件地图中的文档 + 目标文件 + 其测试（先读后改）
② 拆解  输出改动计划：涉及文件 / 新增测试 / 需同步的文档，确认后动手
③ 红    写失败测试（TDD 起点）
④ 绿    最小实现通过测试
⑤ 验    本地 make check（lint + format + test + 覆盖率）+ 相关 E2E 场景
⑥ 文档  同步 SDD / 接口清单 / 提示词回归样本
⑦ 安全  security.md 自检清单全部勾选
⑧ 提交  Conventional Commits（feat:/fix:/test:/docs:…）
```

## 常用命令速查（完整版见 development.md §1.2；命令失败先检查对应文件是否存在）

```bash
make check                       # 本地一键自检（lint+format+test+coverage）
cd backend && pytest -x -q       # 后端单测
cd backend && ruff check .       # lint
cd frontend && pnpm lint         # 前端检查
cd e2e && npx playwright test    # 全链路回归
alembic upgrade head             # 迁移
```

## AI 代理护栏（常见错误预防）

- **不要假设路径/文件存在**：动手前用 Glob / ls 确认；命令失败先查文件，不硬试。
- **不要跳过测试**：任何功能改动必须有对应测试；"改动小所以不测"不成立。
- **不要顺手重构**：与任务无关的重构/格式化改动禁止混入 PR。
- **破坏性操作须声明**：`rm -rf`、`alembic downgrade`、`git reset --hard`、`git push --force` 必须先说明意图与影响范围，经确认后执行。
- **会话无记忆**：跨文件的重要决策写入 `docs/decisions/` 或代码注释，供后续会话接力。
- **LLM 相关开发**：测试中一律 mock LLM，禁止真实调用（耗钱且不稳定）。

---

*详细规约请按文件地图进入对应文档。* 首次接到任务时，建议从 `docs/agents/development.md §1（基本要求）` 开始。
