"""审计服务单测 — 审计日志查询（过滤下推/倒序分页/LEFT JOIN 操作人姓名）."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.audit_log import AuditLog
from app.services import audit_service

MEMBER_ID = uuid.uuid4()
PROJECT_ID = uuid.uuid4()


def _log(**overrides) -> AuditLog:
    defaults = {
        "id": uuid.uuid4(),
        "user_id": MEMBER_ID,
        "action": "kb.material_delete",
        "project_id": None,
        "target_type": "document",
        "target_id": "doc-1",
        "detail": {"from": "a", "to": "b"},
        "created_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return AuditLog(**defaults)


def _count_result(total: int) -> MagicMock:
    result = MagicMock()
    result.scalar.return_value = total
    return result


def _rows_result(rows: list) -> MagicMock:
    result = MagicMock()
    result.all.return_value = rows
    return result


class TestQueryLogs:
    @pytest.mark.asyncio
    async def test_filters_and_ordering_pushed_to_sql(self) -> None:
        """全部过滤条件下推 SQL；先 count 后 items；created_at 倒序分页."""
        db = AsyncMock()
        db.execute.side_effect = [_count_result(0), _rows_result([])]
        await audit_service.query_logs(
            db,
            page=2,
            page_size=5,
            action="kb.",
            user_id=MEMBER_ID,
            project_id=PROJECT_ID,
            target_type="document",
            start=datetime(2026, 1, 1),
            end=datetime(2026, 12, 31),
        )
        assert db.execute.await_count == 2
        stmts = " ".join(str(c.args[0]) for c in db.execute.await_args_list)
        assert "LIKE" in stmts  # action 前缀匹配
        assert "user_id" in stmts
        assert "project_id" in stmts
        assert "target_type" in stmts
        assert "DESC" in stmts  # created_at 倒序

    @pytest.mark.asyncio
    async def test_returns_items_and_total(self) -> None:
        """返回契约：items 序列化 dict + total（LEFT JOIN 操作人姓名）."""
        db = AsyncMock()
        db.execute.side_effect = [_count_result(1), _rows_result([(_log(), "张三")])]
        items, total = await audit_service.query_logs(db, page=1, page_size=20)
        assert total == 1
        assert len(items) == 1
        item = items[0]
        assert item["action"] == "kb.material_delete"
        assert item["user_name"] == "张三"
        assert item["detail"] == {"from": "a", "to": "b"}
        assert item["user_id"] == str(MEMBER_ID)
        assert item["project_id"] is None

    @pytest.mark.asyncio
    async def test_user_name_empty_when_join_miss(self) -> None:
        """用户已删除（LEFT JOIN 未命中）→ user_name 空串."""
        db = AsyncMock()
        db.execute.side_effect = [_count_result(1), _rows_result([(_log(), None)])]
        items, _ = await audit_service.query_logs(db, page=1, page_size=20)
        assert items[0]["user_name"] == ""

    @pytest.mark.asyncio
    async def test_project_id_serialized_when_present(self) -> None:
        """project_id 非空时序列化为字符串."""
        db = AsyncMock()
        db.execute.side_effect = [
            _count_result(1),
            _rows_result([(_log(project_id=PROJECT_ID), None)]),
        ]
        items, _ = await audit_service.query_logs(db, page=1, page_size=20)
        assert items[0]["project_id"] == str(PROJECT_ID)
