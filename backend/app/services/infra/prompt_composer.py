"""PromptComposer — DSL 配置 → 最终提示词组装引擎.

读取 YAML 模板（支持两种格式）：
1. 旧格式（扁平）：system_prompt + user_prompt（str.format 占位符），向后兼容
2. DSL 格式：system_prompt.base + fragments[when] + user_prompt.sections[when]

Sprint 1 阶段：兼容旧格式，使用 str.format 占位符渲染（等价于 prompt_loader.py 现有逻辑）
Sprint 2 后：YAML 模板迁移为 DSL 格式后，使用条件片段 + 格式化器渲染

对外接口：compose(template_name, context) → (system_prompt, user_prompt)
"""

from pathlib import Path
from typing import Any

import yaml

from app.core.exceptions import BizError
from app.services.infra.expr_evaluator import ExprEvaluator
from app.services.infra.prompt_formatter import PromptFormatter

_PROMPTS_DIR = Path(__file__).resolve().parents[3] / "prompts"


class PromptComposer:
    """DSL 提示词组装引擎.

    读取 YAML 模板 → 按 when 条件组装 system_prompt + user_prompt → 返回最终提示词。
    支持旧格式（扁平 str.format）和 DSL 格式（base + fragments + sections）。
    """

    def __init__(self) -> None:
        self._eval = ExprEvaluator()
        self._fmt = PromptFormatter()
        self._cache: dict[str, dict[str, Any]] = {}

    def compose(self, template_name: str, context: dict[str, Any]) -> tuple[str, str]:
        """组装提示词.

        Args:
            template_name: 模板名（如 "chapter", "outline"）
            context: 渲染上下文（包含 chapter_title, score_points 等数据）

        Returns:
            (system_prompt, user_prompt) 字符串

        Raises:
            BizError: 模板文件不存在
        """
        config = self._load_template(template_name)

        # 判断是 DSL 格式还是旧格式
        sp = config.get("system_prompt")
        up = config.get("user_prompt")

        if isinstance(sp, dict) or isinstance(up, dict):
            # DSL 格式
            system = self._compose_system(sp, context)
            user = self._compose_user(up, context)
        else:
            # 旧格式（扁平 str.format）
            system = self._compose_legacy_system(sp, context)
            user = self._compose_legacy_user(up, context)

        return system, user

    def _load_template(self, name: str) -> dict[str, Any]:
        """加载 YAML 模板（带缓存）."""
        if name in self._cache:
            return self._cache[name]
        try:
            text = (_PROMPTS_DIR / f"{name}.yaml").read_text(encoding="utf-8")
        except FileNotFoundError:
            raise BizError(code=5009, message=f"提示词模板 {name}.yaml 不存在") from None
        config: dict[str, Any] = yaml.safe_load(text)
        self._cache[name] = config
        return config

    # ── DSL 格式组装 ──

    def _compose_system(self, sp_config: dict[str, Any] | None, context: dict[str, Any]) -> str:
        """组装 system_prompt（DSL 格式：base + fragments）."""
        if not sp_config:
            return ""
        parts: list[str] = [sp_config.get("base", "")]
        for frag in sp_config.get("fragments", []):
            when = frag.get("when")
            if self._eval.evaluate(when, context):
                parts.append(frag.get("template", ""))
        return "\n".join(p for p in parts if p)

    def _compose_user(self, up_config: dict[str, Any] | None, context: dict[str, Any]) -> str:
        """组装 user_prompt（DSL 格式：sections）."""
        if not up_config:
            return ""
        parts: list[str] = []
        for section in up_config.get("sections", []):
            when = section.get("when")
            if not self._eval.evaluate(when, context):
                continue
            # 有 label 的 section 先加标签
            label = section.get("label", "")
            # 获取数据
            source = section.get("source")
            format_name = section.get("format", "raw")
            template = section.get("template")

            if template is not None:
                # 静态文本片段
                if label:
                    parts.append(f"{label}\n{template}")
                else:
                    parts.append(template)
            elif source is not None:
                # 数据驱动 section
                data = context.get(source, "")
                # 格式化：列表类型按指定 format 格式化，字符串/其他类型走 raw
                if isinstance(data, list):
                    formatted = self._fmt.format(format_name, data) if data else ""
                elif data:
                    formatted = self._fmt.format("raw", data)
                else:
                    formatted = ""
                if formatted:
                    if label:
                        parts.append(f"{label}\n{formatted}")
                    else:
                        parts.append(formatted)
        return "\n\n".join(parts)

    # ── 旧格式兼容（str.format 占位符）──

    def _compose_legacy_system(self, sp: str | None, context: dict[str, Any]) -> str:
        """旧格式 system_prompt（直接返回，不做条件判断）."""
        return sp or ""

    def _compose_legacy_user(self, up: str | None, context: dict[str, Any]) -> str:
        """旧格式 user_prompt（str.format 占位符渲染）."""
        if not up:
            return ""
        # 提取占位符名称，只传存在的键（避免 KeyError）
        import re

        placeholders = re.findall(r"\{(\w+)\}", up)
        fmt_ctx: dict[str, Any] = {}
        for key in placeholders:
            val = context.get(key, "")
            # 如果值是 list/dict 且格式化器有对应格式，先格式化
            if isinstance(val, list) and val:
                # 猜测格式：list[dict] with clause_no → score_point_list
                if isinstance(val[0], dict):
                    if "clause_no" in val[0] and "strategy" in val[0]:
                        fmt_ctx[key] = self._fmt.format("risk_list", val)
                    elif "clause_no" in val[0]:
                        fmt_ctx[key] = self._fmt.format("score_point_list", val)
                    elif "chapter_no" in val[0] and "summary" in val[0]:
                        fmt_ctx[key] = self._fmt.format("summary_list", val)
                    elif "term" in val[0]:
                        fmt_ctx[key] = self._fmt.format("glossary_list", val)
                    elif "category" in val[0] and "description" in val[0]:
                        fmt_ctx[key] = self._fmt.format("requirement_list", val)
                    else:
                        fmt_ctx[key] = str(val)
                elif isinstance(val[0], str):
                    fmt_ctx[key] = self._fmt.format("bullet_list", val)
            else:
                fmt_ctx[key] = val if val else "（无）"
        return up.format(**fmt_ctx)
