"""Skill zip 导入导出 — 三重防护（S4，对齐 OpenMAIC）.

**为什么单列一个模块**：zip 解析是本次改造里**唯一处理不可信二进制**的入口
（用户上传的任意文件）。把它与 CRUD 服务分开，才能让安全断言聚焦在单文件上、
也便于「畸形 zip 用例」穷举。

三重防护
--------
1. **体积上限**（解压前判，不是解压后）：``SKILL_ZIP_MAX_BYTES``
2. **内容硬顶**：条目数 ``SKILL_ZIP_MAX_ENTRIES`` + 累计解压体积
   ``SKILL_ZIP_MAX_UNCOMPRESSED``（防 zip 炸弹）
3. **结构校验 + 路径隔离**：
   - 逐条拒绝 ``..`` / 绝对路径 / 反斜杠 / 符号链接项
   - 只认 ``<name>/SKILL.md`` 这种「恰好一层目录」的结构
   - **不调用 ``extractall``**，逐条 ``read()`` 到内存 —— 全程不落盘，
     天然免疫 zip slip（没有"解压目标路径"这个攻击面）
   - 非 UTF-8 直接拒绝（``errors="strict"``）
   - ``name`` 白名单正则再校验一遍（防 DB 里出现诡异 name）

导出：按 ``<name>/SKILL.md`` 结构打包，内置 skill 默认不导出。
"""

from __future__ import annotations

import io
import logging
import re
import stat
import uuid
import zipfile

from app.core.exceptions import ValidationError
from app.services.skills import registry
from app.services.skills.contract import (
    SKILL_NAME_PATTERN,
    SkillContract,
    SkillContractError,
    parse_skill_md,
    validate_contract,
)

logger = logging.getLogger(__name__)

# ── 防护常量（人工确认项按推荐方案取值）──────────────────────────────
SKILL_ZIP_MAX_BYTES = 1 * 1024 * 1024  # 1 MiB：压缩包本体上限
SKILL_ZIP_MAX_ENTRIES = 50  # 最多 50 个条目
SKILL_ZIP_MAX_UNCOMPRESSED = 5 * 1024 * 1024  # 5 MiB：累计解压上限
MAX_OUTPUT_LENGTH = 70_000  # 对齐 OpenMAIC 的 maxOutputLength

_MD_FILENAME = "SKILL.md"

# 期望结构：<name>/SKILL.md —— 恰好一层目录（不允许多层嵌套 / 根级裸文件）
_ENTRY_PATH_RE = re.compile(r"^([^/]+)/SKILL\.md$")

# 反斜杠与盘符：Windows 路径穿越的变体
_WINDOWS_ABS_RE = re.compile(r"^[a-zA-Z]:")


def _reject_unsafe_path(filename: str) -> None:
    """拒绝不安全路径（穿越 / 绝对路径 / 反斜杠）.

    在**读取内容之前**调用 —— 早失败，不把可疑条目读进内存。
    """
    if not filename or filename.strip() != filename:
        raise ValidationError(f"zip 条目名非法（空或含首尾空白）: {filename!r}")
    if "\\" in filename:
        raise ValidationError(f"zip 条目名含反斜杠，拒绝: {filename!r}")
    if filename.startswith("/") or _WINDOWS_ABS_RE.match(filename):
        raise ValidationError(f"zip 条目名为绝对路径，拒绝: {filename!r}")
    # 逐段检查 `..`（防 `a/../../etc/passwd`）
    for part in filename.split("/"):
        if part in ("..", "."):
            raise ValidationError(f"zip 条目名含路径穿越段，拒绝: {filename!r}")


def _reject_symlink(info: zipfile.ZipInfo) -> None:
    """拒绝符号链接条目（防「链接指向包外文件」）."""
    # ZipInfo.external_attr 高 16 位是 Unix mode
    mode = info.external_attr >> 16
    if mode and stat.S_ISLNK(mode):
        raise ValidationError(f"zip 含符号链接条目，拒绝: {info.filename!r}")


def _read_zip(raw: bytes) -> zipfile.ZipFile:
    """打开 zip（先判体积上限）."""
    if not raw:
        raise ValidationError("zip 内容为空")
    if len(raw) > SKILL_ZIP_MAX_BYTES:
        raise ValidationError(f"zip 超过体积上限：{len(raw)} > {SKILL_ZIP_MAX_BYTES} 字节（1 MiB）")
    try:
        return zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile as e:
        raise ValidationError(f"不是合法的 zip 文件: {e}") from e


def import_skills_zip(raw: bytes, owner_id: uuid.UUID | str | None = None) -> list[SkillContract]:
    """从 zip 解析出 skill 契约列表（**不落库**，由调用方入库）.

    全程内存操作、不落盘、不调用 ``extractall``。

    Args:
        raw: zip 原始字节。
        owner_id: 保留参数（当前用户层全员共享，仅供调用方标记创建者）。

    Returns:
        解析并通过契约校验的 ``SkillContract`` 列表（``builtin=False``）。

    Raises:
        ValidationError: 体积/条目数/路径/编码/结构/契约任一不合规。
    """
    with _read_zip(raw) as zf:
        infos = zf.infolist()
        if len(infos) > SKILL_ZIP_MAX_ENTRIES:
            raise ValidationError(f"zip 条目数超限：{len(infos)} > {SKILL_ZIP_MAX_ENTRIES}")

        total = 0
        results: list[SkillContract] = []
        seen_names: set[str] = set()

        for info in infos:
            _reject_unsafe_path(info.filename)
            _reject_symlink(info)
            # 目录项（以 / 结尾）直接跳过
            if info.is_dir():
                continue

            m = _ENTRY_PATH_RE.match(info.filename)
            if m is None:
                # 只忽略明确无关的文件（如 macOS 的 __MACOSX 元数据）；
                # 其余「像 SKILL.md 但结构不对」的一律拒绝 —— 防靠嵌套绕过校验
                if info.filename.endswith(_MD_FILENAME):
                    raise ValidationError(
                        f"zip 内 SKILL.md 结构非法（须为 <name>/SKILL.md 恰好一层）: "
                        f"{info.filename!r}"
                    )
                continue

            dir_name = m.group(1)
            # 解压后才知真实体积，故读之前先看声明的 file_size（zip 炸弹的第一道）
            if info.file_size > SKILL_ZIP_MAX_UNCOMPRESSED:
                raise ValidationError(
                    f"zip 单品声明体积超限：{info.filename!r} {info.file_size} 字节"
                )
            content = zf.read(info)
            total += len(content)
            if total > SKILL_ZIP_MAX_UNCOMPRESSED:
                raise ValidationError(
                    f"zip 累计解压体积超限：{total} > {SKILL_ZIP_MAX_UNCOMPRESSED}"
                )

            try:
                text = content.decode("utf-8", errors="strict")
            except UnicodeDecodeError as e:
                raise ValidationError(f"SKILL.md 非 UTF-8 编码，拒绝: {info.filename!r}") from e

            try:
                contract = parse_skill_md(text, builtin=False, source_path=info.filename)
                # 目录名必须等于 frontmatter name（与内置层同一契约）
                validate_contract(
                    contract,
                    valid_stage_keys=registry.VALID_STAGE_KEYS,
                    expected_name=dir_name,
                )
            except SkillContractError as e:
                raise ValidationError(f"zip 内契约非法（{info.filename}）: {e}") from e

            # name 白名单再校验一遍（validate_contract 已含，此处防御 DB 侧诡异值）
            if not SKILL_NAME_PATTERN.match(contract.name):
                raise ValidationError(f"zip 内 skill 名非法: {contract.name!r}")
            if contract.name in seen_names:
                raise ValidationError(f"zip 内 skill 名重复: {contract.name!r}")
            seen_names.add(contract.name)

            results.append(contract)

        if not results:
            raise ValidationError("zip 内未找到任何合法 skill（期望结构：<name>/SKILL.md）")
        return results


def export_skills_zip(
    contracts: list[SkillContract],
    *,
    include_builtin: bool = False,
) -> bytes:
    """把 skill 契约打成 zip（``<name>/SKILL.md``）.

    Args:
        contracts: 待导出契约。
        include_builtin: 是否包含内置层（默认不含 —— 内置随代码分发，导出无意义）。

    Returns:
        zip 字节。

    Raises:
        ValidationError: 无可导出内容。
    """
    picked = [c for c in contracts if include_builtin or not c.builtin]
    if not picked:
        raise ValidationError(
            "没有可导出的 skill（内置 skill 默认不导出；如需导出请传 include_builtin=true）"
        )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for c in picked:
            # 复用契约层的渲染源，保证「导出 → 导入」逐字节可还原
            zf.writestr(f"{c.name}/{_MD_FILENAME}", _to_skill_md(c))
    return buf.getvalue()


def _to_skill_md(c: SkillContract) -> str:
    """契约 → SKILL.md 文本（与 loader 的读取格式对称）."""
    import yaml

    meta: dict[str, object] = {
        "name": c.name,
        "title": c.title,
        "description": c.description,
        "version": c.version,
        "stage_key": c.stage_key,
    }
    if not c.user_invocable:
        meta["user-invocable"] = False
    if c.agent_id:
        meta["agent_id"] = c.agent_id
    if c.metadata:
        meta["metadata"] = c.metadata

    front = yaml.safe_dump(
        meta, allow_unicode=True, sort_keys=False, default_flow_style=False
    ).rstrip("\n")
    return f"---\n{front}\n---\n\n{c.body}\n"


__all__ = [
    "MAX_OUTPUT_LENGTH",
    "SKILL_ZIP_MAX_BYTES",
    "SKILL_ZIP_MAX_ENTRIES",
    "SKILL_ZIP_MAX_UNCOMPRESSED",
    "export_skills_zip",
    "import_skills_zip",
]
