"""Rerank 精排服务 — 云端 API（DashScope gte-rerank 兼容协议）.

检索链路：pgvector 召回（top_k 放宽）→ rerank(query, candidates) 精排 → 取头部。

直通（不外发）：LLM mock 模式 / BID_RERANK_ENABLED=false / 未配置 api_key / 空候选。
降级：API 异常或响应结构非法 → 返回原向量序，不抛异常、不阻塞检索链路。
安全（项目铁律）：候选文本与查询外发前经 redact 脱敏；api_key 仅入请求头，
禁止出现在日志与明文文档中。
"""

import asyncio
import logging

import httpx

from app.core.config import settings
from app.core.redact import redact
from app.services import settings_service
from app.services.rag_service import ChunkResult

logger = logging.getLogger(__name__)

RERANK_TIMEOUT_SECS = 10.0  # 云端 rerank 超时上限（超时即降级原序）


def _post_rerank(url: str, headers: dict, payload: dict, timeout: float) -> dict:
    """同步 HTTP POST（经 asyncio.to_thread 调用，避免阻塞事件循环）."""
    resp = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


async def rerank(
    query: str,
    candidates: list[ChunkResult],
    *,
    top_n: int | None = None,
) -> list[ChunkResult]:
    """对召回候选按相关度精排（降序），失败/直通时返回原序.

    top_n: 非 None 时截断前 N 条（精排后截断，保证头部质量）。
    """
    if not candidates:
        return []
    # 直通场景：mock 模式保持确定性；未启用/无密钥不外发
    if await settings_service.is_mock_enabled():
        return candidates
    if not settings.rerank_enabled or not settings.rerank_api_key:
        return candidates

    try:
        payload = {
            "model": settings.rerank_model,
            # 外发前脱敏（安全铁律）：查询与候选文本均经 redact
            "input": {
                "query": redact(query),
                "documents": [redact(c.content) for c in candidates],
            },
        }
        headers = {
            "Authorization": f"Bearer {settings.rerank_api_key}",
            "Content-Type": "application/json",
        }
        data = await asyncio.to_thread(
            _post_rerank, settings.rerank_api_base, headers, payload, RERANK_TIMEOUT_SECS
        )

        results = data.get("output", {}).get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            logger.warning("rerank 响应结构非法，降级返回原向量序")
            return candidates

        scored: list[tuple[float, int]] = []
        seen: set[int] = set()
        for item in results:
            if not isinstance(item, dict):
                continue
            idx = item.get("index")
            score = item.get("relevance_score")
            if not isinstance(idx, int) or not (0 <= idx < len(candidates)) or idx in seen:
                continue
            if not isinstance(score, int | float):
                continue
            seen.add(idx)
            scored.append((float(score), idx))

        if not scored:
            return candidates

        scored.sort(key=lambda pair: pair[0], reverse=True)
        ordered = [candidates[idx] for _, idx in scored]
        # 远程未覆盖的候选按原序补尾（不丢弃素材）
        ordered.extend(c for i, c in enumerate(candidates) if i not in seen)
        return ordered[:top_n] if top_n else ordered
    except Exception as e:
        # 降级不阻塞检索：记录异常类型即可，不回显响应细节（防密钥/素材泄漏）
        logger.warning("rerank 调用失败，降级返回原向量序: %s: %s", type(e).__name__, e)
        return candidates
