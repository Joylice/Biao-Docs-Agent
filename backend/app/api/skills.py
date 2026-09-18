"""Skill 管理 API 路由（挂 /settings/skills 前缀，S4）.

**门禁口径**：全部端点仅要求「登录用户」（``get_current_user_id``），
**不使用 ``get_current_admin_id``** —— 这是与 ``external_tools.py`` 的关键差异：
外部工具配的是全局密钥（必须 admin），skill 是「我的行为准则」这种用户级资产，
普通用户就该能维护自己的（产品口径②B「用户层全员共享」）。

**写操作固定三连**（照抄 external_tools 范式）：
    await audit.record(...)   → 留痕
    await db.commit()         → 落库
    registry.invalidate()     → 清用户层缓存（否则 30s TTL 内读到旧值）

**内置层只读**：``builtin=True`` 的 skill 删除/更新一律 403 —— 覆盖内置是
「改 backend/skills/ 文件」这种发布动作，不是运行期操作。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.database import get_db
from app.core.deps import get_current_user_id
from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.core.response import success
from app.schemas.skills import SkillCreate, SkillPreviewBody, SkillUpdate
from app.services.skills import registry
from app.services.skills import service as skills_service
from app.services.skills.contract import (
    SKILL_BODY_MAX_CHARS,
    SkillContract,
    SkillContractError,
    render_skill_prompt,
    validate_contract,
)
from app.services.skills.loader import load_builtin_skills
from app.services.skills.zip_io import export_skills_zip, import_skills_zip

logger = logging.getLogger(__name__)

router = APIRouter()


def _assert_not_builtin(name: str, action: str) -> None:
    """纯内置（无用户覆盖行的内置 skill）只读门禁.

    ⚠️ **本函数只负责「不是可改对象」这一种拒绝**，请勿在此放行内置名 ——
    内置层有同名**不代表**可改：用户层有没有覆盖行才是判据（覆盖行可改可删，
    只有内置行则是发布动作、必须 403）。

    历史缺陷：曾有 `if name in load_builtin_skills(): return` 的提前放行，
    导致 `PUT /outline` / `DELETE /outline` / `POST /outline/reset` 全部绕过
    只读门禁、直接落到 service 层，返回 404（"用户级准则 'outline' 不存在"）
    而非 403。**顺序错位的门禁 = 没有门禁**，故改为调用方先判用户层行：

        if not await _user_row_exists(db, name):
            _assert_not_builtin(name, "修改")
    """
    raise ForbiddenError(
        f"不能{action}内置准则 '{name}'：它是只读的系统准则，"
        f"且当前没有你的覆盖行；如需修改请调整 backend/skills/ 下的文件"
    )


async def _user_row_exists(db: AsyncSession, name: str) -> bool:
    """用户层是否有该 name 的行（有 → 可改可删；无 → 可能是纯内置）."""
    try:
        await skills_service.get_skill(db, name)
        return True
    except Exception:  # NotFoundError（及其他）→ 视为不存在
        return False


# ── 列表 / 详情 ────────────────────────────────────────────────────


@router.get("")
async def list_skills_api(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """列出全量 skill（内置 + 用户层合并，内置带 ``builtin=true`` 只读标记）.

    合并规则由 registry 保证：**同名时用户层覆盖内置**；``enabled=False``
    的用户 skill 视为不存在（回退内置）—— 故这里额外列出「被禁用」的行，
    否则用户看不到自己禁用的 skill、也就无法重新启用。
    """
    merged = await registry.list_skills(db, user_id)
    enabled_user = {c.name for c in merged if not c.builtin}

    builtin_names = set(load_builtin_skills())
    items: list[dict[str, Any]] = []

    # 用户层全量（含 disabled）—— 视图需要展示待启用项
    rows = await skills_service.list_skill_rows(db)
    shown: set[str] = set()
    for row in rows:
        view = skills_service.row_to_view(row)
        # 被 user-invocable=False 内置挡住的行：如实标记为「未生效」，不隐藏
        view["effective"] = view["name"] in enabled_user
        items.append(view)
        shown.add(row.name)

    # 内置层（未被用户行覆盖的）
    for name, c in sorted(load_builtin_skills().items()):
        if name in shown:
            continue
        view = skills_service.contract_to_view(c, editable=c.user_invocable)
        view["effective"] = True
        items.append(view)

    items.sort(key=lambda v: (not v["builtin"], v["name"]))
    logger.info("列出 skill: user_id=%s 内置=%d 用户=%d", user_id, len(builtin_names), len(rows))
    return success(
        data={
            "items": items,
            "builtinCount": len(builtin_names),
            "userCount": len(rows),
            "bodyMaxChars": SKILL_BODY_MAX_CHARS,
            "stageKeys": sorted(registry.VALID_STAGE_KEYS),
        }
    )


@router.get("/export")
async def export_skills_api(
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
    include_builtin: bool = Query(default=False, description="是否含内置 skill"),
) -> Response:
    """导出 skill 为 zip（``<name>/SKILL.md``）.

    ⚠️ 路由顺序：本端点必须声明在 ``/{name}`` **之前**，否则 "export" 会被
    当作 name 参数匹配走详情分支。
    """
    contracts = await registry.list_skills(db, user_id)
    raw = export_skills_zip(contracts, include_builtin=include_builtin)
    logger.info("导出 skill zip: user_id=%s 字节=%d", user_id, len(raw))
    return Response(
        content=raw,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="skills.zip"'},
    )


@router.get("/{name}")
async def get_skill_api(
    name: str,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """单个 skill 详情（含 body）."""
    contract = await registry.find_skill(name, db, user_id)
    if contract is None:
        # NotFoundError 的形参是 resource，会自动拼「…不存在」
        raise NotFoundError(f"准则 '{name}'")

    if contract.builtin:
        view = skills_service.contract_to_view(contract, editable=contract.user_invocable)
        view["effective"] = True
        return success(data=view)

    row = await skills_service.get_skill(db, name)
    view = skills_service.row_to_view(row)
    view["effective"] = True
    return success(data=view)


# ── 写操作 ─────────────────────────────────────────────────────────


@router.post("")
async def create_skill_api(
    req: SkillCreate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """创建用户级 skill（人工创建 → 直接启用）."""
    row = await skills_service.create_skill(
        db,
        name=req.name,
        title=req.title,
        description=req.description,
        stage_key=req.stage_key,
        body_md=req.body_md,
        agent_id=req.agent_id,
        metadata=req.metadata,
        owner_id=user_id,
        created_by="user",
    )

    await audit.record(
        db,
        user_id,
        "skills.create",
        target_type="user_skill",
        target_id=row.name,
        detail={
            "name": row.name,
            "stage_key": row.stage_key,
            "body_chars": len(row.body_md),
            "created_by": row.created_by,
        },
    )
    await db.commit()
    registry.invalidate()

    return success(data=skills_service.row_to_view(row), message="准则已创建")


@router.put("/{name}")
async def update_skill_api(
    name: str,
    req: SkillUpdate,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """更新用户级 skill（三态 + 乐观锁）."""
    if not await _user_row_exists(db, name):
        _assert_not_builtin(name, "修改")

    row = await skills_service.update_skill(
        db,
        name,
        title=req.title,
        description=req.description,
        body_md=req.body_md,
        enabled=req.enabled,
        metadata=req.metadata,
        expected_version=req.expected_version,
    )

    changed = [
        k
        for k, v in req.model_dump(exclude_unset=True).items()
        if k != "expected_version" and v is not None
    ]
    await audit.record(
        db,
        user_id,
        "skills.update",
        target_type="user_skill",
        target_id=name,
        detail={"name": name, "fields": changed, "version": row.version},
    )
    await db.commit()
    registry.invalidate()

    return success(data=skills_service.row_to_view(row), message="准则已更新")


@router.delete("/{name}")
async def delete_skill_api(
    name: str,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """删除用户级 skill（纯内置 → 403）."""
    if not await _user_row_exists(db, name):
        _assert_not_builtin(name, "删除")

    await skills_service.delete_skill(db, name)

    await audit.record(
        db,
        user_id,
        "skills.delete",
        target_type="user_skill",
        target_id=name,
        detail={"name": name},
    )
    await db.commit()
    registry.invalidate()

    return success(message="准则已删除")


@router.post("/{name}/reset")
async def reset_skill_api(
    name: str,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """「恢复内置」= 删除用户层覆盖.

    无同名内置时等同删除 —— 此时语义是「清掉这个自建准则」。
    """
    if not await _user_row_exists(db, name):
        _assert_not_builtin(name, "重置")

    has_builtin = name in load_builtin_skills()
    await skills_service.reset_skill(db, name)

    await audit.record(
        db,
        user_id,
        "skills.reset",
        target_type="user_skill",
        target_id=name,
        detail={"name": name, "restored_builtin": has_builtin},
    )
    await db.commit()
    registry.invalidate()

    msg = "已恢复为内置准则" if has_builtin else "自建准则已清除"
    return success(message=msg)


# ── 导入 / 预览 ────────────────────────────────────────────────────


@router.post("/import")
async def import_skills_api(
    file: UploadFile = File(description="按 <name>/SKILL.md 结构打包的 zip"),
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """zip 导入（三重防护见 ``services/skills/zip_io.py``）.

    同名已存在时**不覆盖**，如实回报 ``created=false`` —— 静默覆盖是危险默认值
    （用户导入一份旧包会把线上准则冲掉）。
    """
    raw = await file.read()
    parsed = import_skills_zip(raw, owner_id=user_id)

    results: list[dict[str, Any]] = []
    for c in parsed:
        try:
            row = await skills_service.create_skill(
                db,
                name=c.name,
                title=c.title,
                description=c.description,
                stage_key=c.stage_key,
                body_md=c.body,
                agent_id=c.agent_id,
                metadata=c.metadata,
                owner_id=user_id,
                created_by="user",
            )
            results.append({"name": row.name, "created": True, "message": "已导入"})
        except Exception as e:  # 逐个失败不阻断整包，如实回报
            logger.warning("zip 导入单条失败: name=%s err=%s", c.name, e)
            results.append({"name": c.name, "created": False, "message": str(e)})

    created = sum(1 for r in results if r["created"])
    await audit.record(
        db,
        user_id,
        "skills.import",
        target_type="user_skill",
        detail={
            "total": len(results),
            "created": created,
            "names": [r["name"] for r in results],
            "bytes": len(raw),
        },
    )
    await db.commit()
    registry.invalidate()

    return success(
        data={"items": results, "total": len(results), "created": created},
        message=f"导入完成：成功 {created} / 共 {len(results)}",
    )


@router.post("/preview")
async def preview_skill_api(
    req: SkillPreviewBody,
    user_id: uuid.UUID = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """预览渲染结果（**不落库**）—— 看最终 system/user 提示词.

    用途：用户在编辑器里改到一半就想确认「这条准则渲染出来到底长什么样」。
    ``name`` 命中注册表时用线上契约的 metadata（保证注入区与运行时一致），
    仅用 ``body_md`` 覆盖正文；未命中则按草稿造一个最小契约。
    """
    base: SkillContract | None = None
    if req.name:
        base = await registry.find_skill(req.name, db, user_id)

    if base is not None:
        draft = SkillContract(
            name=base.name,
            title=req.title or base.title,
            description=req.description or base.description,
            version=base.version,
            stage_key=req.stage_key or base.stage_key,
            body=req.body_md,
            user_invocable=base.user_invocable,
            agent_id=base.agent_id,
            metadata=base.metadata,
            builtin=False,
        )
    else:
        draft = SkillContract(
            name=req.name or "preview_draft",
            title=req.title or "预览草稿",
            description=req.description or "预览草稿",
            version="0.0.0",
            stage_key=req.stage_key or "outline",
            body=req.body_md,
            builtin=False,
        )

    try:
        validate_contract(draft, valid_stage_keys=registry.VALID_STAGE_KEYS)
    except SkillContractError as e:
        raise ValidationError(f"草稿契约非法：{e}") from e

    system_prompt, user_prompt = render_skill_prompt(draft, req.context)
    return success(
        data={
            "name": draft.name,
            "systemPrompt": system_prompt,
            "userPrompt": user_prompt,
            "systemChars": len(system_prompt),
            "userChars": len(user_prompt),
            "resolvedFrom": "registry" if base is not None else "draft",
        }
    )


__all__ = ["router"]
