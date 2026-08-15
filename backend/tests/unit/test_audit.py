"""审计日志模块测试 — AuditLog 模型元数据 + audit.record() 封装（无需真实 DB）."""

import uuid
from unittest.mock import MagicMock

from app.core import audit
from app.models import AuditLog


class TestAuditLogModel:
    """audit_logs 表元数据检查."""

    def test_table_name(self) -> None:
        assert AuditLog.__tablename__ == "audit_logs"

    def test_required_columns(self) -> None:
        cols = AuditLog.__table__.columns
        for name in (
            "id",
            "user_id",
            "action",
            "project_id",
            "target_type",
            "target_id",
            "detail",
            "created_at",
        ):
            assert name in cols, f"缺少列 {name}"

    def test_no_soft_delete(self) -> None:
        """追加式表：禁止软删/更新时间字段."""
        cols = AuditLog.__table__.columns
        for name in ("deleted_at", "is_deleted", "updated_at"):
            assert name not in cols, f"audit_logs 为追加式表，不应有列 {name}"

    def test_user_id_and_action_required(self) -> None:
        assert AuditLog.__table__.c.user_id.nullable is False
        assert AuditLog.__table__.c.action.nullable is False

    def test_optional_columns_nullable(self) -> None:
        for name in ("project_id", "target_type", "target_id", "detail"):
            assert AuditLog.__table__.c[name].nullable is True, f"列 {name} 应可为空"

    def test_detail_is_json(self) -> None:
        from sqlalchemy import JSON

        assert isinstance(AuditLog.__table__.c.detail.type, JSON)

    def test_created_at_server_default(self) -> None:
        assert AuditLog.__table__.c.created_at.server_default is not None


class TestAuditRecord:
    """audit.record() 封装行为."""

    async def test_record_adds_log_to_session(self) -> None:
        """record 将 AuditLog 加入 session."""
        session = MagicMock()
        user_id = uuid.uuid4()
        project_id = uuid.uuid4()

        log = await audit.record(
            session,
            user_id,
            "auth.login",
            project_id=project_id,
            target_type="user",
            target_id=str(user_id),
            detail={"ip": "127.0.0.1"},
        )

        session.add.assert_called_once()
        added = session.add.call_args.args[0]
        assert isinstance(added, AuditLog)
        assert added.user_id == user_id
        assert added.action == "auth.login"
        assert added.project_id == project_id
        assert added.target_type == "user"
        assert added.target_id == str(user_id)
        assert added.detail == {"ip": "127.0.0.1"}
        assert log is added

    async def test_record_optional_defaults(self) -> None:
        """可选参数缺省时为 None."""
        session = MagicMock()
        user_id = uuid.uuid4()

        log = await audit.record(session, user_id, "workflow.export")

        assert log is not None
        assert log.project_id is None
        assert log.target_type is None
        assert log.target_id is None
        assert log.detail is None

    async def test_sensitive_keys_stripped_from_detail(self) -> None:
        """detail 中敏感字段不落库."""
        session = MagicMock()
        user_id = uuid.uuid4()

        log = await audit.record(
            session,
            user_id,
            "auth.login",
            detail={
                "password": "p@ss",
                "api_key": "sk-xxx",
                "token": "jwt...",
                "secret": "s3cret",
                "email": "a@b.com",
            },
        )

        assert log is not None
        assert log.detail is not None
        for key in ("password", "api_key", "token", "secret"):
            assert key not in log.detail, f"敏感字段 {key} 不应落库"
        assert log.detail["email"] == "a@b.com"

    async def test_nested_sensitive_keys_stripped(self) -> None:
        """嵌套 dict 中的敏感字段同样被剥离."""
        session = MagicMock()

        log = await audit.record(
            session,
            uuid.uuid4(),
            "document.upload",
            detail={"meta": {"password": "x", "filename": "a.pdf"}},
        )

        assert log is not None
        assert log.detail == {"meta": {"filename": "a.pdf"}}

    async def test_record_failure_does_not_raise(self) -> None:
        """审计写入失败仅记 warning，不阻断业务."""
        session = MagicMock()
        session.add.side_effect = RuntimeError("db broken")

        log = await audit.record(session, uuid.uuid4(), "auth.login")

        assert log is None
