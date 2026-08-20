"""术语表服务 — 阶段 E2（SDD §6.1/§6.4）.

glossary 条目 [{term, canonical, desc}]：parse 阶段 LLM 抽取落 documents.meta，
生成阶段注入 chapter.yaml 提示词，integrate 阶段规则替换统一术语。
"""

# mock 模式 schema 产出的占位术语，替换会污染正文，直接跳过
_SKIP_TERMS = {"", "mock"}


def unify_terms(text: str, glossary: list[dict]) -> str:
    """按术语表把 term 统一替换为 canonical（占位/非法条目跳过）."""
    if not text or not glossary:
        return text
    for entry in glossary:
        term = (entry.get("term") or "").strip()
        canonical = (entry.get("canonical") or "").strip()
        if not term or not canonical or term in _SKIP_TERMS or term == canonical:
            continue
        text = text.replace(term, canonical)
    return text
