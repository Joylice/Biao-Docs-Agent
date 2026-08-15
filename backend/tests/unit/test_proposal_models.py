"""Proposal 系列模型定义测试（元数据检查，无需真实 DB）."""

from sqlalchemy import UniqueConstraint

from app.models import (
    ProposalSection,
    ProposalSkeleton,
    ProposalWorkflow,
    Review,
)


class TestProposalWorkflowModel:
    """proposal_workflows 表."""

    def test_table_name(self) -> None:
        assert ProposalWorkflow.__tablename__ == "proposal_workflows"

    def test_required_columns(self) -> None:
        cols = ProposalWorkflow.__table__.columns
        for name in ("id", "project_id", "phase", "progress", "status", "thread_id", "updated_at"):
            assert name in cols, f"缺少列 {name}"

    def test_project_id_unique(self) -> None:
        uniques = ProposalWorkflow.__table__.constraints
        assert any(
            isinstance(c, UniqueConstraint) and sorted(c.columns.keys()) == ["project_id"]
            for c in uniques
        ), "project_id 应为唯一约束（每项目一个工作流）"

    def test_default_phase(self) -> None:
        assert ProposalWorkflow.__table__.c.phase.default is not None

    def test_default_status(self) -> None:
        assert ProposalWorkflow.__table__.c.status.default is not None


class TestProposalSkeletonModel:
    """proposal_skeletons 表."""

    def test_table_name(self) -> None:
        assert ProposalSkeleton.__tablename__ == "proposal_skeletons"

    def test_required_columns(self) -> None:
        cols = ProposalSkeleton.__table__.columns
        for name in ("id", "project_id", "tree", "created_at"):
            assert name in cols, f"缺少列 {name}"

    def test_project_id_unique(self) -> None:
        uniques = ProposalSkeleton.__table__.constraints
        assert any(
            isinstance(c, UniqueConstraint) and sorted(c.columns.keys()) == ["project_id"]
            for c in uniques
        ), "project_id 应为唯一约束（每项目一个骨架）"


class TestProposalSectionModel:
    """proposal_sections 表."""

    def test_table_name(self) -> None:
        assert ProposalSection.__tablename__ == "proposal_sections"

    def test_required_columns(self) -> None:
        cols = ProposalSection.__table__.columns
        for name in (
            "id",
            "project_id",
            "section_id",
            "title",
            "content_md",
            "status",
            "citations",
        ):
            assert name in cols, f"缺少列 {name}"

    def test_project_section_unique(self) -> None:
        uniques = ProposalSection.__table__.constraints
        assert any(
            isinstance(c, UniqueConstraint)
            and sorted(c.columns.keys()) == ["project_id", "section_id"]
            for c in uniques
        ), "project_id+section_id 应为联合唯一约束"

    def test_default_status(self) -> None:
        assert ProposalSection.__table__.c.status.default is not None


class TestReviewModel:
    """reviews 表."""

    def test_table_name(self) -> None:
        assert Review.__tablename__ == "reviews"

    def test_required_columns(self) -> None:
        cols = Review.__table__.columns
        for name in ("id", "project_id", "section_id", "action", "content", "created_by"):
            assert name in cols, f"缺少列 {name}"
