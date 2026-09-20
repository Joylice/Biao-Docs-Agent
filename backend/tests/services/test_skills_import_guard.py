"""Skill zip 导入端点的 API 层体积预检（S4 收尾加固）.

防御纵深：``zip_io.import_skills_zip`` 的 1 MiB 检查发生在
``await file.read()`` **之后** —— 攻击者可先让超大 body 全量进内存再被拒
（认证后 DoS 面）。API 层须在 read **之前**按 ``file.size`` 拒绝。

测试手法：假 UploadFile 的 ``read()`` 一被调就抛 AssertionError ——
预检在 read 前 → 不会触发 → 仅 ValidationError（绿）；
无预检 → read 被调 → AssertionError（红）。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from app.core.exceptions import ValidationError
from app.services.skills.zip_io import SKILL_ZIP_MAX_BYTES

_OVERSIZE = SKILL_ZIP_MAX_BYTES + 1


class _BoomUpload:
    """size 超限、read 即炸的假上传文件."""

    def __init__(self) -> None:
        self.size: int | None = _OVERSIZE
        self.filename = "big.zip"
        self.content_type = "application/zip"

    async def read(self) -> bytes:
        raise AssertionError("超限文件不应被读入内存（预检须发生在 read 之前）")


class _OversizeThenValid:
    """size 属性缺失（None）时必须退回 read 后判断 —— 不得绕过."""

    def __init__(self) -> None:
        self.size: int | None = None
        self.filename = "unknown.zip"
        self.content_type = "application/zip"

    async def read(self) -> bytes:
        return b"x" * _OVERSIZE


def _call_import(file: Any) -> Any:
    from app.api.skills import import_skills_api

    return asyncio.run(import_skills_api(file=file, user_id=uuid.uuid4(), db=None))


class TestImportSizePrecheck:
    def test_rejects_oversize_before_read(self) -> None:
        """size 超限 → read 之前拒绝（预检核心断言）."""
        with pytest.raises(ValidationError, match="超过体积上限"):
            _call_import(_BoomUpload())

    def test_falls_back_to_post_read_check_when_size_unknown(self) -> None:
        """size 未知（None）→ 仍由 zip_io 的 read 后检查兜底，不绕过."""
        with pytest.raises(ValidationError, match="超过体积上限"):
            _call_import(_OversizeThenValid())
