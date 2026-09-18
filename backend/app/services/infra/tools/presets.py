"""外部工具预设定义 — Tavily / Brave / SearXNG 的 auth_style 与 response_path 映射.

预设决定密钥注入方式与响应路径提取，自定义工具走 custom（用户自填 base_url）。
"""

from dataclasses import dataclass, field


@dataclass
class ToolPreset:
    """工具预设配置 — 决定密钥注入方式与响应路径.

    - default_base_url: 预设默认请求地址（None 表示用户必须自填）
    - requires_key: 是否需要 API Key（searxng 不需要）
    - auth_style: 密钥注入方式（bearer_body / header_token / none）
    - auth_header: header_token 模式下的请求头名（如 X-Subscription-Token）
    - response_path: 响应 JSON 中结果列表的点分路径（如 "results" / "web.results"）
    - result_mapping: 原始结果字段 → 统一输出字段映射
    """

    default_base_url: str | None
    requires_key: bool
    auth_style: str
    auth_header: str
    response_path: str
    result_mapping: dict[str, str] = field(
        default_factory=lambda: {
            "title": "title",
            "url": "url",
            "content": "content",
        }
    )


# 预设工具注册表：preset 名 → ToolPreset
PRESET_TOOLS: dict[str, ToolPreset] = {
    "tavily": ToolPreset(
        default_base_url="https://api.tavily.com",
        requires_key=True,
        auth_style="bearer_body",
        auth_header="",
        response_path="results",
        result_mapping={
            "title": "title",
            "url": "url",
            "content": "content",
        },
    ),
    "brave": ToolPreset(
        default_base_url="https://api.search.brave.com/res/v1/web/search",
        requires_key=False,
        auth_style="header_token",
        auth_header="X-Subscription-Token",
        response_path="web.results",
        result_mapping={
            "title": "title",
            "url": "url",
            "content": "description",
        },
    ),
    "searxng": ToolPreset(
        default_base_url=None,
        requires_key=False,
        auth_style="none",
        auth_header="",
        response_path="results",
        result_mapping={
            "title": "title",
            "url": "url",
            "content": "content",
        },
    ),
    "custom": ToolPreset(
        default_base_url=None,
        requires_key=False,
        auth_style="none",
        auth_header="",
        response_path="results",
        result_mapping={
            "title": "title",
            "url": "url",
            "content": "content",
        },
    ),
}
