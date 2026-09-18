"""外部工具 HTTP 客户端 — 异步调用搜索 API，按 auth_style 注入密钥.

设计要点：
- 输入截断：query.strip()[:tool.max_query_chars] 防注入；
- SSRF 校验：base_url 走 security._validate_api_base()，拒绝内网/本机目标；
- auth_style 三档：bearer_body → JSON body 加 api_key；header_token → headers；none → 不注入；
- 降级策略：非 200 / 超时 / JSON 解析失败 / 响应路径缺失 → logger.warning + 返回
  [{"error": ...}]，不抛异常（保证 LLM tool_call 循环不中断）；
- result_mapping 统一输出为 [{title, url, content}]。
"""

import logging
from typing import Any

import httpx

from app.models.external_tool import ExternalTool
from app.services.infra.settings.security import _validate_api_base
from app.services.infra.tools.presets import PRESET_TOOLS, ToolPreset

logger = logging.getLogger(__name__)


def _extract_by_path(data: dict[str, Any], path: str) -> list[Any]:
    """按点分路径从嵌套 dict 中提取列表（如 "web.results"）."""
    current: Any = data
    for key in path.split("."):
        if not isinstance(current, dict):
            return []
        current = current.get(key)
        if current is None:
            return []
    return current if isinstance(current, list) else []


def _map_results(raw_list: list[Any], mapping: dict[str, str]) -> list[dict[str, Any]]:
    """将原始结果按 result_mapping 映射为统一输出 [{title, url, content}]."""
    mapped: list[dict[str, Any]] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        title = item.get(mapping.get("title", "title"), "")
        url = item.get(mapping.get("url", "url"), "")
        content = item.get(mapping.get("content", "content"), "")
        mapped.append(
            {
                "title": str(title) if title is not None else "",
                "url": str(url) if url is not None else "",
                "content": str(content) if content is not None else "",
            }
        )
    return mapped


async def call_external_tool(
    tool: ExternalTool, api_key: str | None, query: str
) -> list[dict[str, Any]]:
    """调用外部搜索工具，返回统一格式结果列表.

    异常/超时/响应异常均降级为 [{"error": "..."}]，不抛异常。
    """
    preset_name = tool.preset or "custom"
    preset: ToolPreset | None = PRESET_TOOLS.get(preset_name)
    if preset is None:
        preset = PRESET_TOOLS["custom"]

    # ① 输入截断
    truncated_query = query.strip()[: tool.max_query_chars]

    # ② base_url 解析 + SSRF 校验
    base_url = tool.base_url or preset.default_base_url
    if not base_url:
        logger.warning("外部工具 %s 无 base_url（preset=%s 且未自填）", tool.name, preset_name)
        return [{"error": f"{preset_name} 调用失败: 缺少 base_url"}]
    try:
        _validate_api_base(base_url, "base_url")
    except Exception as exc:
        logger.warning("外部工具 %s base_url SSRF 校验失败: %s", tool.name, exc)
        return [{"error": f"{preset_name} 调用失败: SSRF 校验拒绝"}]

    # ③ 按 auth_style 构造请求
    timeout_s = tool.timeout_ms / 1000.0
    headers: dict[str, str] = {"Content-Type": "application/json"}
    body: dict[str, Any] = {"query": truncated_query}

    if preset.auth_style == "bearer_body":
        if not api_key:
            logger.warning("外部工具 %s 需要 api_key 但未配置", tool.name)
            return [{"error": f"{preset_name} 调用失败: 缺少 api_key"}]
        body["api_key"] = api_key
    elif preset.auth_style == "header_token":
        if api_key:
            headers[preset.auth_header] = api_key
    # none → 不注入

    # ④ 发起 HTTP 请求
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(base_url, json=body, headers=headers)
    except httpx.TimeoutException:
        logger.warning("外部工具 %s 请求超时（%dms）", tool.name, tool.timeout_ms)
        return [{"error": f"{preset_name} 调用失败: 请求超时"}]
    except httpx.RequestError as exc:
        logger.warning("外部工具 %s 请求失败: %s", tool.name, exc)
        return [{"error": f"{preset_name} 调用失败: 网络错误"}]

    # ⑤ 非 200 降级
    if response.status_code != 200:
        logger.warning("外部工具 %s 返回非 200 状态码: %d", tool.name, response.status_code)
        return [{"error": f"{preset_name} 调用失败: HTTP {response.status_code}"}]

    # ⑥ JSON 解析
    try:
        data = response.json()
    except Exception:
        logger.warning("外部工具 %s 响应 JSON 解析失败", tool.name)
        return [{"error": f"{preset_name} 调用失败: 响应非 JSON"}]
    if not isinstance(data, dict):
        logger.warning("外部工具 %s 响应非 dict: %s", tool.name, type(data).__name__)
        return [{"error": f"{preset_name} 调用失败: 响应格式异常"}]

    # ⑦ 按 response_path 提取结果列表
    raw_results = _extract_by_path(data, preset.response_path)
    if not raw_results:
        logger.warning("外部工具 %s 响应路径 '%s' 无结果", tool.name, preset.response_path)
        return [{"error": f"{preset_name} 调用失败: 响应路径无结果"}]

    # ⑧ result_mapping 统一输出
    return _map_results(raw_results, preset.result_mapping)
