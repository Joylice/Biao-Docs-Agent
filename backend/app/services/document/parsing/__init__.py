"""解析多智能体子包（parsing/）— T1.1 产出.

模块划分与单向依赖：
  windows.py    窗口选择 / 文本抽取          → core.exceptions
  results.py    ParsedTender / AgentResult    → （无依赖）
  registry.py   4 Agent 配置                 → results（类型引用）
  prompts.py    提示词适配（组数据）          → infra.prompt_loader
  guard.py      三层防御 + Agent 工具白名单    → registry
  dispatch.py   并行调度 + 两段式 + 降级       → windows/registry/prompts/guard/results
                                               → infra.llm_service
  extract.py    【P4】云 OCR 提取兜底          → （P1 不含，P4 新增）

依赖方向铁律：
  dispatch → prompts → infra.prompt_loader → infra.prompt_composer
  dispatch → guard → registry
  dispatch → results → （纯 dataclass）
  dispatch → windows → core.exceptions
  dispatch → infra.llm_service（仅运行时 import，避免循环依赖）

外部兼容：
  parse_service.py 作为门面 re-export 所有公共符号，
  保证 `from app.services.document.parse_service import X` 不变。
  monkeypatch 语义：parse_service.X = mock 仍有效（门面属性透传）。
"""
