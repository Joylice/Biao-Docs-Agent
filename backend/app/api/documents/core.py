"""文档 API 共享定义 — 请求体 schema（第一轮-2 路由薄化拆包）.

自原 api/documents.py 拆分：仅放跨子路由共享的 Pydantic body，
常量与清洗逻辑已下沉 service 层（document_service / dq_service）。
"""

from typing import Any

from pydantic import BaseModel


class FormatRequirementsBody(BaseModel):
    """格式要求保存请求体 — 完整数组幂等覆盖."""

    format_requirements: list[dict[str, Any]]


class DisqualificationClausesBody(BaseModel):
    """废标条款保存请求体 — 完整数组幂等覆盖（阶段 H）."""

    items: list[dict[str, Any]]


__all__ = ["DisqualificationClausesBody", "FormatRequirementsBody"]
