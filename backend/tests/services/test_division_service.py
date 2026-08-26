"""division_service 单元测试 — 子节展开分配、树形分工列表、最小粒度编辑权限.

DB 会话以 AsyncMock + execute 序列模拟（与 API 测试同模式）。
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.exceptions import BizError
from app.models.project import Project, ProjectMember
from app.models.proposal import ChapterAssignment, ProposalSkeleton
from app.models.user import User
from app.services.project import division_service

PROJECT_ID = uuid.uuid4()
OWNER_ID = uuid.uuid4()
MEMBER_ID = uuid.uuid4()
OTHER_ID = uuid.uuid4()


def _result(scalar: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar
    return result


def _scalars_result(rows: list) -> MagicMock:
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = rows
    result.scalars.return_value = scalars
    return result


def _project() -> Project:
    return Project(id=PROJECT_ID, name="测试项目", owner_id=OWNER_ID, status="active")


def _member_row() -> ProjectMember:
    return ProjectMember(project_id=PROJECT_ID, user_id=MEMBER_ID)


def _session(seq: list) -> AsyncMock:
    session = AsyncMock()
    session.execute.side_effect = seq
    session.add = MagicMock()
    return session


def _nested_skeleton() -> ProposalSkeleton:
    """嵌套大纲：章 1 含子节（含三级），章 2 为 string[] 旧形态."""
    return ProposalSkeleton(
        project_id=PROJECT_ID,
        tree=[
            {
                "chapter_no": "1",
                "title": "项目概述",
                "sections": [
                    {"title": "项目背景"},
                    {"title": "建设目标", "children": [{"title": "总体目标"}]},
                ],
            },
            {"chapter_no": "2", "title": "技术方案", "sections": ["旧格式子节"]},
        ],
    )


class TestAssignChapters:
    @pytest.mark.asyncio
    async def test_assign_new_chapter_adds_pending(self) -> None:
        """新分配（无骨架）：add + flush，状态 pending."""
        session = _session(
            [
                _result(None),  # _load_outline 无骨架
                _result(_project()),  # _is_project_member 查 project
                _result(_member_row()),  # 成员表命中
                _result(None),  # 无既有分工
            ]
        )
        assignments = await division_service.assign_chapters(
            session,
            PROJECT_ID,
            OWNER_ID,
            [{"chapter_no": "1", "title": "项目概述", "assignee_id": str(MEMBER_ID)}],
        )
        assert len(assignments) == 1
        assert assignments[0].status == "pending"
        assert assignments[0].assignee_id == MEMBER_ID
        session.add.assert_called_once()
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_assign_existing_resets_status(self) -> None:
        """幂等 upsert：既有分工更新负责人并重置流转状态."""
        existing = ChapterAssignment(
            project_id=PROJECT_ID,
            chapter_no="1",
            title="旧标题",
            assignee_id=OTHER_ID,
            assigned_by=OWNER_ID,
            status="submitted",
            review_comment="旧意见",
        )
        session = _session(
            [
                _result(None),  # 无骨架
                _result(_project()),
                _result(_member_row()),
                _result(existing),
            ]
        )
        assignments = await division_service.assign_chapters(
            session,
            PROJECT_ID,
            OWNER_ID,
            [{"chapter_no": "1", "title": "新标题", "assignee_id": str(MEMBER_ID)}],
        )
        updated = assignments[0]
        assert updated is existing
        assert updated.status == "pending"
        assert updated.assignee_id == MEMBER_ID
        assert updated.title == "新标题"
        assert updated.review_comment is None
        session.add.assert_not_called()

    @pytest.mark.asyncio
    async def test_assign_non_member_raises_4004(self) -> None:
        """assignee 非项目成员 → 4004."""
        session = _session(
            [
                _result(None),
                _result(_project()),  # owner 判定不通过（OTHER 非 owner）
                _result(None),  # 成员表未命中
            ]
        )
        with pytest.raises(BizError) as exc:
            await division_service.assign_chapters(
                session,
                PROJECT_ID,
                OWNER_ID,
                [{"chapter_no": "1", "title": "项目概述", "assignee_id": str(OTHER_ID)}],
            )
        assert exc.value.code == 4004

    @pytest.mark.asyncio
    async def test_assign_missing_fields_raises_4000(self) -> None:
        session = _session([_result(None)])
        with pytest.raises(BizError) as exc:
            await division_service.assign_chapters(
                session, PROJECT_ID, OWNER_ID, [{"chapter_no": "1"}]
            )
        assert exc.value.code == 4000

    @pytest.mark.asyncio
    async def test_assign_chapter_expands_to_subsections(self) -> None:
        """章级分配 + 嵌套大纲 → 自动展开全部子节（含三级编号），不保留章级行."""
        member_seq = [_result(_project()), _result(_member_row()), _result(None)]
        session = _session(
            [
                _result(_nested_skeleton()),  # 骨架
                _result(None),  # 无旧章级分工
                *member_seq,  # 子节 1.1
                *member_seq,  # 子节 1.2
                *member_seq,  # 子节 1.2.1
            ]
        )
        assignments = await division_service.assign_chapters(
            session,
            PROJECT_ID,
            OWNER_ID,
            [{"chapter_no": "1", "title": "项目概述", "assignee_id": str(MEMBER_ID)}],
        )
        assert [a.chapter_no for a in assignments] == ["1.1", "1.2", "1.2.1"]
        assert [a.title for a in assignments] == ["项目背景", "建设目标", "总体目标"]
        assert session.add.call_count == 3

    @pytest.mark.asyncio
    async def test_assign_expansion_deletes_stale_chapter_row(self) -> None:
        """章级分工展开为子节时，旧章级分工记录被替换删除."""
        stale = ChapterAssignment(
            project_id=PROJECT_ID,
            chapter_no="1",
            title="项目概述",
            assignee_id=OTHER_ID,
            assigned_by=OWNER_ID,
            status="in_progress",
        )
        member_seq = [_result(_project()), _result(_member_row()), _result(None)]
        session = _session(
            [
                _result(_nested_skeleton()),
                _result(stale),  # 旧章级分工命中 → 删除
                *member_seq,
                *member_seq,
                *member_seq,
            ]
        )
        await division_service.assign_chapters(
            session,
            PROJECT_ID,
            OWNER_ID,
            [{"chapter_no": "1", "title": "项目概述", "assignee_id": str(MEMBER_ID)}],
        )
        session.delete.assert_awaited_once_with(stale)

    @pytest.mark.asyncio
    async def test_assign_string_sections_keeps_chapter_level(self) -> None:
        """string[] 大纲（无嵌套子节）→ 保持章级分配不展开."""
        session = _session(
            [
                _result(_nested_skeleton()),
                _result(_project()),
                _result(_member_row()),
                _result(None),
            ]
        )
        assignments = await division_service.assign_chapters(
            session,
            PROJECT_ID,
            OWNER_ID,
            [{"chapter_no": "2", "title": "技术方案", "assignee_id": str(MEMBER_ID)}],
        )
        assert [a.chapter_no for a in assignments] == ["2"]

    @pytest.mark.asyncio
    async def test_assign_subsection_directly(self) -> None:
        """子节编号（1.1）可直接分配，不再二次展开."""
        session = _session(
            [
                _result(_nested_skeleton()),
                _result(_project()),
                _result(_member_row()),
                _result(None),
            ]
        )
        assignments = await division_service.assign_chapters(
            session,
            PROJECT_ID,
            OWNER_ID,
            [{"chapter_no": "1.1", "title": "项目背景", "assignee_id": str(MEMBER_ID)}],
        )
        assert [a.chapter_no for a in assignments] == ["1.1"]


def _assignment(no: str, assignee_id, status: str = "pending") -> ChapterAssignment:
    return ChapterAssignment(
        id=uuid.uuid4(),
        project_id=PROJECT_ID,
        chapter_no=no,
        title=f"标题{no}",
        assignee_id=assignee_id,
        assigned_by=OWNER_ID,
        status=status,
    )


class TestListAssignments:
    @pytest.mark.asyncio
    async def test_list_aggregates_children_under_chapter(self) -> None:
        """章级聚合行：子节分工挂 children，附 approved_count/total 聚合字段."""
        user = User(id=MEMBER_ID, email="m@x.com", password_hash="x", display_name="张三")
        sub = _assignment("1.1", MEMBER_ID, status="approved")
        join_result = MagicMock()
        join_result.all.return_value = [(sub, user, "draft")]
        session = _session([join_result, _result(_nested_skeleton())])

        items = await division_service.list_assignments(session, PROJECT_ID)
        assert len(items) == 1
        chapter = items[0]
        assert chapter["chapter_no"] == "1"
        assert chapter["id"] is None, "无章级分工时章行为聚合行（无 id）"
        assert chapter["total"] == 1
        assert chapter["approved_count"] == 1
        assert chapter["status"] == "approved", "全部子节 approved → 聚合 approved"
        assert chapter["children"][0]["chapter_no"] == "1.1"
        assert chapter["children"][0]["assignee_name"] == "张三"

    @pytest.mark.asyncio
    async def test_list_aggregate_status_priority(self) -> None:
        """聚合状态优先级：submitted > rejected > in_progress > pending."""
        user = User(id=MEMBER_ID, email="m@x.com", password_hash="x", display_name="张三")
        rows = [
            (_assignment("1.1", MEMBER_ID, status="approved"), user, None),
            (_assignment("1.2", MEMBER_ID, status="in_progress"), user, None),
        ]
        join_result = MagicMock()
        join_result.all.return_value = rows
        session = _session([join_result, _result(_nested_skeleton())])

        items = await division_service.list_assignments(session, PROJECT_ID)
        assert items[0]["status"] == "in_progress"
        assert items[0]["approved_count"] == 1
        assert items[0]["total"] == 2

    @pytest.mark.asyncio
    async def test_list_own_assignment_with_children(self) -> None:
        """章级分工与子节分工并存：章行保留自身字段并挂 children."""
        user = User(id=MEMBER_ID, email="m@x.com", password_hash="x", display_name="张三")
        own = _assignment("1", MEMBER_ID, status="in_progress")
        sub = _assignment("1.1", MEMBER_ID, status="pending")
        join_result = MagicMock()
        join_result.all.return_value = [(own, user, None), (sub, user, None)]
        session = _session([join_result, _result(_nested_skeleton())])

        items = await division_service.list_assignments(session, PROJECT_ID)
        assert len(items) == 1
        assert items[0]["id"] == str(own.id)
        assert items[0]["status"] == "in_progress"
        assert items[0]["total"] == 1

    @pytest.mark.asyncio
    async def test_list_flat_when_no_skeleton(self) -> None:
        """无骨架（工作流未确认大纲）→ 退回扁平分工列表."""
        user = User(id=MEMBER_ID, email="m@x.com", password_hash="x", display_name="张三")
        assignment = _assignment("1", MEMBER_ID, status="in_progress")
        join_result = MagicMock()
        join_result.all.return_value = [(assignment, user, "draft")]
        session = _session([join_result, _result(None)])

        items = await division_service.list_assignments(session, PROJECT_ID)
        assert len(items) == 1
        assert items[0]["chapter_no"] == "1"
        assert items[0]["section_status"] == "draft"
        assert items[0]["children"] == []


class TestCheckChapterEditable:
    @pytest.mark.asyncio
    async def test_unassigned_chapter_owner_only(self) -> None:
        """无任何分工 → 收紧为仅 owner 可编辑（需求 3）."""

        def seq() -> list:
            return [
                _result(None),  # 精确匹配无分工
                _scalars_result([]),  # 无子节分工
                _result(_project()),  # owner 兜底判定
            ]

        assert await division_service.check_chapter_editable(
            _session(seq()), PROJECT_ID, "9", OWNER_ID
        )
        assert not await division_service.check_chapter_editable(
            _session(seq()), PROJECT_ID, "9", OTHER_ID
        )

    @pytest.mark.asyncio
    async def test_unassigned_chapter_owner_flag_short_circuit(self) -> None:
        """is_owner=True 短路不查库."""
        session = _session([])
        assert await division_service.check_chapter_editable(
            session, PROJECT_ID, "9", OWNER_ID, is_owner=True
        )
        session.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_assignee_editable(self) -> None:
        session = _session([_result(_assignment("1", MEMBER_ID))])
        assert await division_service.check_chapter_editable(session, PROJECT_ID, "1", MEMBER_ID)

    @pytest.mark.asyncio
    async def test_owner_editable(self) -> None:
        session = _session([_result(_assignment("1", MEMBER_ID))])
        assert await division_service.check_chapter_editable(
            session, PROJECT_ID, "1", OWNER_ID, is_owner=True
        )

    @pytest.mark.asyncio
    async def test_other_member_not_editable(self) -> None:
        """已分配章节：非 assignee 且非 owner → 不可编辑（可视不可改）."""
        session = _session([_result(_assignment("1", MEMBER_ID)), _result(_project())])
        assert not await division_service.check_chapter_editable(session, PROJECT_ID, "1", OTHER_ID)

    @pytest.mark.asyncio
    async def test_owner_fallback_editable(self) -> None:
        """未传 is_owner 时 owner 经兜底查询仍可编辑."""
        session = _session([_result(_assignment("1", MEMBER_ID)), _result(_project())])
        assert await division_service.check_chapter_editable(session, PROJECT_ID, "1", OWNER_ID)

    @pytest.mark.asyncio
    async def test_subsection_inherits_parent_assignment(self) -> None:
        """子节无分工但父章有分工 → 父章 assignee 可编辑该子节（章级覆盖子节）."""
        session = _session(
            [
                _result(None),  # 1.1 无分工
                _result(_assignment("1", MEMBER_ID)),  # 父章 1 有分工
            ]
        )
        assert await division_service.check_chapter_editable(session, PROJECT_ID, "1.1", MEMBER_ID)

    @pytest.mark.asyncio
    async def test_subsection_other_member_forbidden(self) -> None:
        """子节由他人负责 → 其他成员不可编辑."""
        session = _session(
            [
                _result(_assignment("1.1", MEMBER_ID)),  # 子节已分配给张三
                _result(_project()),  # owner 兜底（李四非 owner）
            ]
        )
        assert not await division_service.check_chapter_editable(
            session, PROJECT_ID, "1.1", OTHER_ID
        )

    @pytest.mark.asyncio
    async def test_chapter_editable_by_child_assignee(self) -> None:
        """章下存在子节分工 → 子节 assignee 可编辑整章."""
        child = _assignment("1.1", MEMBER_ID)
        session = _session(
            [
                _result(None),  # 章级无分工
                _scalars_result([child]),  # 子节分工命中
            ]
        )
        assert await division_service.check_chapter_editable(session, PROJECT_ID, "1", MEMBER_ID)

    @pytest.mark.asyncio
    async def test_chapter_with_children_other_member_forbidden(self) -> None:
        """章下子节均已分配他人 → 普通成员不可编辑整章."""
        child = _assignment("1.1", MEMBER_ID)
        session = _session(
            [
                _result(None),
                _scalars_result([child]),
                _result(_project()),  # owner 兜底（非 owner）
            ]
        )
        assert not await division_service.check_chapter_editable(session, PROJECT_ID, "1", OTHER_ID)
