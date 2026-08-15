"""task_service 单测 — mock arq pool 断言入队参数；Redis 不可用时降级不抛异常."""

import uuid

import pytest

from app.services import task_service

PROJECT_ID = uuid.uuid4()
DOC_ID = uuid.uuid4()


class FakePool:
    """模拟 arq ArqRedis 连接池."""

    def __init__(self) -> None:
        self.jobs: list[tuple] = []
        self.redis_settings = None
        self.closed = False

    async def enqueue_job(self, job_name, *args, **kwargs):
        self.jobs.append((job_name, args, kwargs))

    async def aclose(self) -> None:
        self.closed = True


@pytest.fixture
def fake_pool(monkeypatch):
    pool = FakePool()

    async def fake_create_pool(redis_settings):
        pool.redis_settings = redis_settings
        return pool

    monkeypatch.setattr("arq.create_pool", fake_create_pool)
    return pool


@pytest.mark.asyncio
async def test_enqueue_parse_tender_calls_pool(fake_pool) -> None:
    """招标文件解析任务入队：任务名与位置参数正确，池用后关闭."""
    ok = await task_service.enqueue_parse_tender(PROJECT_ID, DOC_ID)
    assert ok is True
    assert fake_pool.jobs == [("task_parse_tender", (str(PROJECT_ID), str(DOC_ID)), {})]
    assert fake_pool.redis_settings is not None
    assert fake_pool.closed is True


@pytest.mark.asyncio
async def test_enqueue_index_document_calls_pool(fake_pool) -> None:
    """资料库文档向量化任务入队：任务名与位置参数正确."""
    ok = await task_service.enqueue_index_document(PROJECT_ID, DOC_ID)
    assert ok is True
    assert fake_pool.jobs == [("task_index_document", (str(PROJECT_ID), str(DOC_ID)), {})]
    assert fake_pool.closed is True


@pytest.mark.asyncio
async def test_redis_unavailable_degrades_without_raise(monkeypatch) -> None:
    """Redis 连接失败时降级：不抛异常，返回 False."""

    async def broken_create_pool(redis_settings):
        raise ConnectionError("Redis 不可用")

    monkeypatch.setattr("arq.create_pool", broken_create_pool)
    ok = await task_service.enqueue_parse_tender(PROJECT_ID, DOC_ID)
    assert ok is False

    ok = await task_service.enqueue_index_document(PROJECT_ID, DOC_ID)
    assert ok is False
