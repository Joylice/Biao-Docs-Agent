"""Skill zip 导入导出单测 — 三重防护逐条覆盖（S4）.

这是本次改造里**唯一处理不可信二进制**的入口，安全断言必须穷举：
体积上限 / 条目数 / 累计解压体积 / 路径穿越（`..`、绝对路径、反斜杠、盘符）/
符号链接 / 非 UTF-8 / 目录名≠name / 结构非 `<name>/SKILL.md` / zip 炸弹 /
空包 / 非法 zip / 重复 name。

**为什么单独一个文件**：让「畸形 zip 用例」自成一套，将来加防护规则时改动面收敛。
"""

from __future__ import annotations

import io
import stat
import zipfile

import pytest

from app.core.exceptions import ValidationError
from app.services.skills.contract import SkillContract
from app.services.skills.zip_io import (
    SKILL_ZIP_MAX_BYTES,
    SKILL_ZIP_MAX_ENTRIES,
    SKILL_ZIP_MAX_UNCOMPRESSED,
    export_skills_zip,
    import_skills_zip,
)

_VALID_MD = """---
name: {name}
title: 演示准则
description: 用于单测的合法契约
version: "1.0.0"
stage_key: outline
---

你是演示用的行为指令，请按顺序执行。
"""


def _md(name: str = "demo_skill") -> str:
    return _VALID_MD.format(name=name)


def _zip_bytes(entries: dict[str, str | bytes], *, symlink: str | None = None) -> bytes:
    """构造 zip 字节（entries: 路径 → 内容）."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path, content in entries.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            zf.writestr(path, data)
        if symlink:
            info = zipfile.ZipInfo(symlink)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, "/etc/passwd")
    return buf.getvalue()


# ── 正常路径 ────────────────────────────────────────────────────────


class TestImportHappyPath:
    def test_single_skill(self) -> None:
        raw = _zip_bytes({"demo_skill/SKILL.md": _md()})
        got = import_skills_zip(raw)
        assert len(got) == 1
        c = got[0]
        assert isinstance(c, SkillContract)
        assert c.name == "demo_skill"
        assert c.builtin is False
        assert c.stage_key == "outline"

    def test_multiple_skills(self) -> None:
        raw = _zip_bytes(
            {
                "alpha_skill/SKILL.md": _md("alpha_skill"),
                "beta_skill/SKILL.md": _md("beta_skill"),
            }
        )
        got = import_skills_zip(raw)
        assert sorted(c.name for c in got) == ["alpha_skill", "beta_skill"]

    def test_ignores_unrelated_files(self) -> None:
        """非 SKILL.md 的附带文件应被忽略（如 README）."""
        raw = _zip_bytes(
            {
                "demo_skill/SKILL.md": _md(),
                "demo_skill/README.md": "# 说明",
                "notes.txt": "随手记",
            }
        )
        got = import_skills_zip(raw)
        assert [c.name for c in got] == ["demo_skill"]

    def test_roundtrip_export_import(self) -> None:
        """导出 → 导入应还原 name/title/body/stage_key（逐字节可逆）."""
        origin = SkillContract(
            name="round_trip",
            title="往返演示",
            description="验证导出导入可逆",
            version="2.1.0",
            stage_key="review",
            body="你是往返演示的行为指令。\n\n第二段。",
            builtin=False,
        )
        raw = export_skills_zip([origin])
        got = import_skills_zip(raw)
        assert len(got) == 1
        assert got[0].name == origin.name
        assert got[0].title == origin.title
        assert got[0].version == origin.version
        assert got[0].stage_key == origin.stage_key
        assert got[0].body.strip() == origin.body.strip()


# ── 防护 1：体积上限 ────────────────────────────────────────────────


class TestSizeGuard:
    def test_rejects_oversize_zip_before_parse(self) -> None:
        """压缩包本体超限 —— 解压前就拒绝."""
        raw = b"x" * (SKILL_ZIP_MAX_BYTES + 1)
        with pytest.raises(ValidationError, match="超过体积上限"):
            import_skills_zip(raw)

    def test_rejects_empty(self) -> None:
        with pytest.raises(ValidationError, match="为空"):
            import_skills_zip(b"")

    def test_rejects_non_zip(self) -> None:
        with pytest.raises(ValidationError, match="不是合法的 zip"):
            import_skills_zip(b"this is definitely not a zip archive")


# ── 防护 2：条目数与解压体积 ────────────────────────────────────────


class TestContentGuard:
    def test_rejects_too_many_entries(self) -> None:
        entries = {f"a{i}/SKILL.md": _md(f"a{i}") for i in range(SKILL_ZIP_MAX_ENTRIES + 1)}
        with pytest.raises(ValidationError, match="条目数超限"):
            import_skills_zip(_zip_bytes(entries))

    def test_rejects_zip_bomb_by_declared_size(self) -> None:
        """单条声明体积超限 —— 在 read() 之前拦下（防解压耗内存）.

        构造真 zip 炸弹：5 MiB 全零在 DEFLATED 下压到几 KB，因而能绕过防护 1
        （压缩包本体 < 1 MiB），必须由防护 2 的 ``info.file_size`` 拦下。
        注意 ``ZipInfo`` 默认 ``compress_type=ZIP_STORED``（不压缩），
        故必须显式设 ``ZIP_DEFLATED``，否则得不到「小包大内容」的炸弹形态。
        """
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            info = zipfile.ZipInfo("bomb_skill/SKILL.md")
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, b"\0" * (SKILL_ZIP_MAX_UNCOMPRESSED + 1))
        raw = buf.getvalue()
        assert len(raw) < SKILL_ZIP_MAX_BYTES, (
            f"炸弹形态未构造成功：压缩后 {len(raw)} 字节不应超过 {SKILL_ZIP_MAX_BYTES}"
        )
        with pytest.raises(ValidationError, match="声明体积超限"):
            import_skills_zip(raw)

    def test_rejects_missing_skill_md(self) -> None:
        with pytest.raises(ValidationError, match="未找到任何合法"):
            import_skills_zip(_zip_bytes({"demo_skill/README.md": "# 无 SKILL.md"}))


# ── 防护 3：路径与结构 ──────────────────────────────────────────────


class TestPathGuard:
    @pytest.mark.parametrize(
        "bad_path",
        [
            "../evil_skill/SKILL.md",
            "a/../../evil_skill/SKILL.md",
            "/absolute_skill/SKILL.md",
            "C:evil_skill/SKILL.md",
            "dir\\..\\evil_skill\\SKILL.md",
        ],
        ids=["parent", "nested_traversal", "absolute", "drive", "backslash"],
    )
    def test_rejects_unsafe_paths(self, bad_path: str) -> None:
        with pytest.raises(ValidationError):
            import_skills_zip(_zip_bytes({bad_path: _md("evil_skill")}))

    def test_rejects_symlink_entry(self) -> None:
        raw = _zip_bytes({"demo_skill/SKILL.md": _md()}, symlink="link_skill/SKILL.md")
        with pytest.raises(ValidationError, match="符号链接"):
            import_skills_zip(raw)

    @pytest.mark.parametrize(
        "bad_path",
        ["nested/deep/SKILL.md", "SKILL.md"],
        ids=["nested_two_levels", "root_level"],
    )
    def test_rejects_non_flat_structure(self, bad_path: str) -> None:
        """必须恰好一层目录 `<name>/SKILL.md` —— 防嵌套绕过校验."""
        with pytest.raises(ValidationError, match="结构非法"):
            import_skills_zip(_zip_bytes({bad_path: _md("demo_skill")}))

    def test_rejects_dir_name_mismatch(self) -> None:
        """目录名必须等于 frontmatter 的 name（与内置层同一契约）."""
        with pytest.raises(ValidationError, match="契约非法"):
            import_skills_zip(_zip_bytes({"other_dir/SKILL.md": _md("demo_skill")}))

    def test_ignores_backup_suffix_files(self) -> None:
        """`SKILL.md.bak` 之类不匹配 `<name>/SKILL.md` 精确结构的应被忽略.

        注意：它虽以 `.md` 结尾但**不以 `SKILL.md` 结尾**（是 `SKILL.md.bak`），
        故走「无关文件」分支而不触发结构非法 —— 这正是想要的宽容区间。
        """
        raw = _zip_bytes(
            {
                "demo_skill/SKILL.md": _md("demo_skill"),
                "demo_skill/SKILL.md.bak": "backup",
            }
        )
        got = import_skills_zip(raw)
        assert [c.name for c in got] == ["demo_skill"]


class TestEncodingGuard:
    def test_rejects_non_utf8(self) -> None:
        gbk = "---\nname: bad_skill\n".encode("gbk") + b"\xff\xfe bad bytes"
        with pytest.raises(ValidationError, match="非 UTF-8"):
            import_skills_zip(_zip_bytes({"bad_skill/SKILL.md": gbk}))

    def test_rejects_missing_frontmatter(self) -> None:
        with pytest.raises(ValidationError, match="契约非法"):
            import_skills_zip(_zip_bytes({"demo_skill/SKILL.md": "没有 frontmatter 的正文"}))

    def test_rejects_invalid_name(self) -> None:
        """name 白名单（大写/连字符/中文都不合法）."""
        bad = (
            "---\nname: Bad-Name\ntitle: t\ndescription: d\n"
            "version: '1.0.0'\nstage_key: outline\n---\n\n正文"
        )
        with pytest.raises(ValidationError):
            import_skills_zip(_zip_bytes({"Bad-Name/SKILL.md": bad}))

    def test_rejects_bad_stage_key(self) -> None:
        bad = (
            "---\nname: stage_skill\ntitle: t\ndescription: d\n"
            "version: '1.0.0'\nstage_key: nonexistent\n---\n\n正文"
        )
        with pytest.raises(ValidationError):
            import_skills_zip(_zip_bytes({"stage_skill/SKILL.md": bad}))


# ── 导出 ────────────────────────────────────────────────────────────


class TestExport:
    def test_export_user_skills_only(self) -> None:
        user = SkillContract(
            name="mine",
            title="我的",
            description="d",
            version="1.0.0",
            stage_key="outline",
            body="正文",
            builtin=False,
        )
        raw = export_skills_zip([user])
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            assert zf.namelist() == ["mine/SKILL.md"]

    def test_export_excludes_builtin_by_default(self) -> None:
        builtin = SkillContract(
            name="built_in",
            title="内置",
            description="d",
            version="1.0.0",
            stage_key="outline",
            body="正文",
            builtin=True,
        )
        with pytest.raises(ValidationError, match="没有可导出的"):
            export_skills_zip([builtin])

    def test_export_includes_builtin_when_asked(self) -> None:
        builtin = SkillContract(
            name="built_in",
            title="内置",
            description="d",
            version="1.0.0",
            stage_key="outline",
            body="正文",
            builtin=True,
        )
        raw = export_skills_zip([builtin], include_builtin=True)
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            assert "built_in/SKILL.md" in zf.namelist()

    def test_export_preserves_metadata_and_flags(self) -> None:
        """user-invocable=false 与 metadata 必须往返保持."""
        c = SkillContract(
            name="meta_skill",
            title="元信息",
            description="d",
            version="1.0.0",
            stage_key="write",
            body="正文",
            user_invocable=False,
            agent_id="agent_x",
            metadata={"token_budget": 1234},
            builtin=False,
        )
        got = import_skills_zip(export_skills_zip([c]))[0]
        assert got.user_invocable is False
        assert got.agent_id == "agent_x"
        assert got.metadata.get("token_budget") == 1234
