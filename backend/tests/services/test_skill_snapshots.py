"""内置 SKILL.md 快照护栏（P3-9）.

S6 删除 4 份 parse_*.yaml 后，S3 的逐字节等价护栏 TestYamlEquivalent
随 YAML 删除自动退役。本测试用 sha256 快照固化全部 10 份内置
SKILL.md 的内容 —— 任何意外改动（含编码/换行/空白）都会被立即发现。

改 SKILL.md 属发布动作，须显式更新快照（重跑生成脚本写新 sha256）。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

_SKILLS_DIR = Path(__file__).resolve().parents[3] / "backend" / "skills"

# 期望结构：<name>/SKILL.md
_EXPECTED = {
    "parse_score",
    "parse_disqual",
    "parse_norm",
    "parse_validator",
    "parse_tender",
    "outline",
    "consistency",
    "review",
    "param_check",
    "chapter",
}


def _read_skill(name: str) -> bytes:
    path = _SKILLS_DIR / name / "SKILL.md"
    assert path.exists(), f"内置 SKILL.md 不存在：{path}"
    return path.read_bytes()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# 快照基线（2026-09-20，S6 收敛后冻结）
_SNAPSHOTS = {
    "parse_score": "5eb3b4560a5b9120604db44a84449f07143b32455fbd2f2e7bc0fd7e5e04d639",
    "parse_disqual": "7e615890de78399d8c8787204f78a71bb5a4553035a5b5c3bed1808930d514f1",
    "parse_norm": "19236b9fd4df6cdcf35697d54628c2231335ec0d566cebe434abe39a8f6aaf22",
    "parse_validator": "3d5bb065482fae6685d60cc61637a4b7a251ef9017a4787137cd3b1e6ec9fb46",
    "parse_tender": "004ec1a4ac2481ea50f27ed915088be2c72aab9e36f8310b0f864edce161b452",
    "outline": "249d4a3fbbdc66e5871de28eb55d4e4350348ce917cecb959f00186f2a0d1ad7",
    "consistency": "75d2f62303597e22fd4bd222160fa8d2fb140dfc7dcf993966eafb11cde06a5e",
    "review": "b77076aaeaaeeed0a7a4cd7f51dca65b49ade2777b76e8e09848ca2eb15ef19b",
    "param_check": "122ac37998d8ba040183298a3a19bb4e424c9b0bc2930a61ac2e1f1a11f9cd24",
    "chapter": "d42fdc3cd4eaf614d0aa1e81ea8bbfc3b104b55a8d4b7ddf9d130247ff5c42ba",
}


class TestSkillSnapshotGuard:
    """改内置 SKILL.md 属发布动作 —— 快照护栏防意外改动。"""

    @pytest.mark.parametrize("name", sorted(_EXPECTED))
    def test_sha256_matches(self, name: str) -> None:
        """内置 SKILL.md 内容 sha256 须与基线一致."""
        actual = _sha256(_read_skill(name))
        assert actual == _SNAPSHOTS[name], (
            f"内置 SKILL.md「{name}」sha256 不匹配：\n"
            f"  期望 {_SNAPSHOTS[name]}\n"
            f"  实际 {actual}\n"
            f"如为有意改动，请更新 _SNAPSHOTS 基线。"
        )

    def test_all_builtin_skills_present(self) -> None:
        """10 份内置 SKILL.md 全部在位（防误删目录）."""
        actual = {p.parent.name for p in _SKILLS_DIR.glob("*/SKILL.md")}
        assert actual == _EXPECTED, (
            f"内置 skill 目录集不匹配：\n  缺失 {_EXPECTED - actual}\n  多余 {actual - _EXPECTED}"
        )
