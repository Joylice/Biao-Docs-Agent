"""三项评测任务：评分点提取准召率 / 方案评分点覆盖 / 检索质量.

任务统一返回 EvalResult；缺 LLM/Embedding Key（且非 mock 模式）时返回 skipped
而非抛异常，保证评测 CLI 在无密钥环境下仍可运行离线任务。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.core.config import settings
from app.services.infra import settings_service
from eval.dataset import (
    load_coverage_datasets,
    load_extraction_datasets,
    load_retrieval_datasets,
)
from eval.metrics import (
    match_score_points,
    precision_recall_f1,
    retrieval_mrr,
    retrieval_recall_at_k,
)

RECALL_K = 8


@dataclass
class EvalResult:
    """单项任务评测结果."""

    task: str
    status: str  # ok / skipped
    metrics: dict[str, float] = field(default_factory=dict)
    details: list[dict] = field(default_factory=list)
    note: str = ""


def _skipped(task: str, note: str) -> EvalResult:
    return EvalResult(task=task, status="skipped", note=note)


async def _model_available(model: str) -> bool:
    """mock 模式直接放行；否则要求库内配置存在对应模型的 API Key."""
    if await settings_service.is_mock_enabled():
        return True
    cfg = await settings_service.get_runtime_config()
    return bool(cfg and cfg.api_key_for(model))


# ── extraction：评分点提取准召率 ──


async def _default_parse(text: str) -> list[dict]:
    """默认提取实现：复用 parse_service 的 LLM 结构化解析链路."""
    from app.services.document.parse_service import parse_tender_with_llm

    parsed = await parse_tender_with_llm(text, include_tech_requirements=False)
    return parsed.score_points


async def run_extraction(datasets: list[dict], parse_fn=None) -> EvalResult:
    """对每个数据集调用提取链路并与 gold 匹配，汇总 P/R/F1."""
    if not datasets:
        return _skipped("extraction", "数据集为空")
    if not await _model_available(settings.llm_model):
        return _skipped("extraction", "LLM 未配置（非 mock 模式且无 API Key），跳过提取评测")
    if parse_fn is None and await settings_service.is_mock_enabled():
        # mock LLM 仅返回占位结构，与 gold 无语义匹配，准召率指标无意义
        return _skipped(
            "extraction",
            "mock 模式 LLM 返回占位数据，提取准召率无意义，跳过（真实评测需配置 API Key）",
        )
    parse = parse_fn or _default_parse

    total_tp = total_fp = total_fn = 0
    details: list[dict] = []
    for ds in datasets:
        preds = await parse(ds["tender_text"])
        counts = match_score_points(ds["gold"]["score_points"], preds)
        total_tp += counts["tp"]
        total_fp += counts["fp"]
        total_fn += counts["fn"]
        details.append({"id": ds["id"], **counts})

    return EvalResult(
        task="extraction",
        status="ok",
        metrics=precision_recall_f1(total_tp, total_fp, total_fn),
        details=details,
    )


# ── coverage：方案评分点覆盖 ──


async def run_coverage(datasets: list[dict]) -> EvalResult:
    """按数据集计算覆盖矩阵（纯离线，无需 Key），coverage_rate 取样本均值."""
    if not datasets:
        return _skipped("coverage", "数据集为空")
    from app.services.proposal.coverage_service import compute_coverage

    rates: list[float] = []
    details: list[dict] = []
    for ds in datasets:
        cov = compute_coverage(ds["score_points"], ds["outline"])
        rates.append(cov["coverage_rate"])
        details.append(
            {
                "id": ds["id"],
                "coverage_rate": cov["coverage_rate"],
                "total": cov["total"],
                "covered": cov["covered"],
                "uncovered_count": len(cov["uncovered"]),
                "uncovered": [sp.get("item", "") for sp in cov["uncovered"]],
            }
        )
    return EvalResult(
        task="coverage",
        status="ok",
        metrics={"coverage_rate": sum(rates) / len(rates)},
        details=details,
    )


# ── retrieval：检索质量 ──


async def _default_search(dataset: dict, query: str) -> list[str]:
    """离线灌库检索：数据集文档登记 documents + 灌入 kb_chunks → 向量召回+精排 → doc 首现序.

    评测用随机 project_id（documents 走 project_id=NULL 全局素材模式，避开 projects 外键），
    不触碰业务数据；threshold=-1 不过滤以便统计排名。doc_uuid 由数据集 id+doc_id 确定性生成，
    插入前先清理旧记录保证重复运行幂等。
    """
    from sqlalchemy import delete

    from app.core.database import async_session_factory
    from app.models.document import Document
    from app.models.kb_chunk import KbChunk
    from app.services.llm import rag_service

    async with async_session_factory() as session:
        project_id = uuid.uuid4()
        doc_uuids: dict[str, uuid.UUID] = {}
        for doc in dataset["docs"]:
            doc_uuid = uuid.uuid5(uuid.NAMESPACE_URL, f"eval:{dataset['id']}:{doc['doc_id']}")
            doc_uuids[doc["doc_id"]] = doc_uuid
            # 幂等清理旧评测记录（kb_chunks.doc_id 外键指向 documents，先删子表）
            await session.execute(delete(KbChunk).where(KbChunk.doc_id == doc_uuid))
            await session.execute(delete(Document).where(Document.id == doc_uuid))
            # kb_chunks.doc_id 外键约束要求 documents 先行登记；project_id=NULL 为全局素材模式
            session.add(
                Document(
                    id=doc_uuid,
                    project_id=None,
                    doc_type="kb_material",
                    title=doc.get("title", doc["doc_id"]),
                    storage_key=f"eval/{dataset['id']}/{doc['doc_id']}",
                    status="indexed",
                )
            )
            embeddings = await rag_service.get_embeddings_batch(doc["chunks"])
            await rag_service.embed_and_store(session, doc_uuid, doc["chunks"], embeddings)
        await session.commit()

        query_embedding = await rag_service.get_embedding(query)
        results = await rag_service.retrieve_with_rerank(
            db=session,
            project_id=project_id,
            query=query,
            query_embedding=query_embedding,
            top_k=RECALL_K,
            threshold=-1.0,
            doc_ids=list(doc_uuids.values()),
        )
        inv = {v: k for k, v in doc_uuids.items()}
        ranked: list[str] = []
        for r in results:
            doc_id = inv[r.doc_id]
            if doc_id not in ranked:
                ranked.append(doc_id)
        return ranked


def _rerank_note() -> str:
    if settings.rerank_enabled and settings.rerank_api_key:
        return "rerank 精排已启用"
    return "rerank 未启用（结果为纯向量召回序）"


async def run_retrieval(datasets: list[dict], search_fn=None) -> EvalResult:
    """对每条查询统计 Recall@8 与 MRR（样本均值）."""
    if not datasets:
        return _skipped("retrieval", "数据集为空")
    if not await _model_available(settings.embedding_model):
        return _skipped("retrieval", "Embedding 未配置（非 mock 模式且无 API Key），跳过检索评测")
    search = search_fn or _default_search

    recalls: list[float] = []
    mrrs: list[float] = []
    details: list[dict] = []
    for ds in datasets:
        for q in ds["queries"]:
            ranked = await search(ds, q["query"])
            relevant = set(q["relevant_doc_ids"])
            recall = retrieval_recall_at_k(ranked, relevant, k=RECALL_K)
            mrr = retrieval_mrr(ranked, relevant)
            recalls.append(recall)
            mrrs.append(mrr)
            details.append(
                {"dataset": ds["id"], "query": q["query"], "recall_at_8": recall, "mrr": mrr}
            )

    return EvalResult(
        task="retrieval",
        status="ok",
        metrics={
            "recall_at_8": sum(recalls) / len(recalls),
            "mrr": sum(mrrs) / len(mrrs),
        },
        details=details,
        note=_rerank_note(),
    )


# ── 目录便捷入口（CLI 使用） ──


async def run_extraction_from_dir(dataset_dir) -> EvalResult:
    return await run_extraction(load_extraction_datasets(dataset_dir))


async def run_coverage_from_dir(dataset_dir) -> EvalResult:
    return await run_coverage(load_coverage_datasets(dataset_dir))


async def run_retrieval_from_dir(dataset_dir) -> EvalResult:
    return await run_retrieval(load_retrieval_datasets(dataset_dir))
