"""数据库引擎与会话管理."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=10,
    max_overflow=20,
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入：获取数据库会话.

    事务约定（BUG-1 修复）：本依赖【不代为 commit】。FastAPI 依赖 teardown
    在响应发出之后才执行，若在 yield 后兜底 commit，会出现"接口已返回 200
    但数据尚未提交"的竞态（注册后立即登录 401、新建项目短暂 404 等）。
    因此：
    - 写路径（含审计写入）必须在返回响应前显式 ``await db.commit()``；
    - 本依赖仅在业务异常时回滚并上抛，会话随上下文退出关闭。
    LangGraph 节点 / worker 任务中经 ``async_session_factory()`` 打开的会话
    遵循同一约定：写块退出前显式 commit。
    """
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
