"""Skills import 端点成功路径与审计测试补强（P3-10）.

既有覆盖：zip_io 层 28 条（四防全覆盖）+ API 层体积预检 2 条（read 前拒）。
缺口：成功导入路径（multipart 上传 → create_skill → audit → commit → invalidate）
和同名不覆盖（created=false）的 API 层行为。
"""

from __future__ import annotations

import io
import uuid
import zipfile
from typing import Any

import pytest

_VALID_MD = """---
name: {name}
title: 演示准则
description: 用于单测的合法契约
version: "1.0.0"
stage_key: outline
---

你是演示用的行为指令，请按顺序执行。
"""


def _make_zip(name: str = "demo_skill") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{name}/SKILL.md", _VALID_MD.format(name=name))
    return buf.getvalue()


class _FakeRow:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeSession:
    """记录 commit 调用（不真连库）."""

    committed = False

    async def commit(self) -> None:
        _FakeSession.committed = True


class TestImportSuccessPath:
    def test_import_creates_skill_and_audits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """合法 zip → 201 + created=true + audit + commit + invalidate."""
        from fastapi.testclient import TestClient

        from app.core import audit
        from app.core.database import get_db
        from app.core.deps import get_current_user_id
        from app.main import app
        from app.services.skills import registry
        from app.services.skills import service as skills_service

        raw = _make_zip("new_skill")

        async def fake_create(_db: Any, **kw: Any) -> Any:
            return _FakeRow(kw["name"])

        create_calls: list[str] = []

        async def capture_create(_db: Any, **kw: Any) -> Any:
            create_calls.append(kw["name"])
            return _FakeRow(kw["name"])

        monkeypatch.setattr(skills_service, "create_skill", capture_create)

        audit_calls: list[dict[str, Any]] = []

        async def capture_audit(_db: Any, uid: Any, action: str, **kw: Any) -> None:
            audit_calls.append({"action": action, **kw})

        monkeypatch.setattr(audit, "record", capture_audit)

        invalidate_called: list[bool] = []

        def capture_invalidate() -> None:
            invalidate_called.append(True)

        monkeypatch.setattr(registry, "invalidate", capture_invalidate)

        _FakeSession.committed = False
        app.dependency_overrides[get_db] = lambda: _FakeSession()
        app.dependency_overrides[get_current_user_id] = lambda: uuid.uuid4()
        try:
            client = TestClient(app)
            r = client.post(
                "/api/v1/settings/skills/import",
                files={"file": ("demo.zip", raw, "application/zip")},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["code"] == 0
            assert body["data"]["created"] == 1
            assert body["data"]["items"][0]["name"] == "new_skill"
            assert body["data"]["items"][0]["created"] is True
            # create_skill 被调一次且 name 对
            assert create_calls == ["new_skill"]
            # audit 留痕
            assert len(audit_calls) == 1
            assert audit_calls[0]["action"] == "skills.import"
            # commit + invalidate 都被调
            assert _FakeSession.committed is True
            assert invalidate_called == [True]
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_current_user_id, None)

    def test_import_same_name_reports_created_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """同名已存在 → created=false 且不覆盖（静默覆盖是危险默认值）."""
        from fastapi.testclient import TestClient

        from app.core import audit
        from app.core.database import get_db
        from app.core.deps import get_current_user_id
        from app.main import app
        from app.services.skills import registry
        from app.services.skills import service as skills_service

        raw = _make_zip("dup_skill")

        async def fake_create_raises(_db: Any, **kw: Any) -> Any:
            raise ValueError("skill name already exists")

        monkeypatch.setattr(skills_service, "create_skill", fake_create_raises)

        async def noop_audit(_db: Any, *_a: Any, **_kw: Any) -> None: ...

        monkeypatch.setattr(audit, "record", noop_audit)
        monkeypatch.setattr(registry, "invalidate", lambda: None)

        app.dependency_overrides[get_db] = lambda: _FakeSession()
        app.dependency_overrides[get_current_user_id] = lambda: uuid.uuid4()
        try:
            client = TestClient(app)
            r = client.post(
                "/api/v1/settings/skills/import",
                files={"file": ("dup.zip", raw, "application/zip")},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["data"]["created"] == 0
            assert body["data"]["items"][0]["name"] == "dup_skill"
            assert body["data"]["items"][0]["created"] is False
        finally:
            app.dependency_overrides.pop(get_db, None)
            app.dependency_overrides.pop(get_current_user_id, None)
