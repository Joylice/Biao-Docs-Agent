"""FastAPI 应用入口."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import (
    annotations,
    audit,
    auth,
    benchmark,
    division,
    documents,
    kb,
    kb_bases,
    projects,
    requirements,
    users,
    versions,
    websocket,
    workbench,
    workflow,
)
from app.api import settings as settings_api
from app.core.config import settings
from app.core.exceptions import BizError
from app.services.infra import workflow_runtime

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期：启动/关闭时的资源管理."""
    # 启动期安全告警（W-2）：默认 jwt_secret 且非 mock 模式 → 显著提醒（不拒启动，
    # 避免破坏测试/开发环境）
    if settings.jwt_secret == "change-me-in-production" and not settings.llm_mock:
        logger.error(
            "安全告警：BID_JWT_SECRET 仍为默认值 'change-me-in-production' 且 llm_mock 已关闭——"
            "JWT 签名与 LLM 密钥加密均不安全！生产环境请立即设置 BID_JWT_SECRET "
            "与 BID_LLM_CRYPTO_SECRET"
        )
    # MinIO 客户端单例 + bucket 初始化
    from app.services.document.storage_service import init_minio

    init_minio()
    # 工作流 checkpointer：AsyncPostgresSaver + 独立连接池（thread_id=project_id）
    await workflow_runtime.init_checkpointer()
    yield
    # 清理资源
    await workflow_runtime.shutdown_checkpointer()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 全局异常处理 ──
@app.exception_handler(BizError)
async def biz_error_handler(_request: Request, exc: BizError) -> JSONResponse:
    """业务异常统一转 JSON."""
    http_status = 400
    if exc.code == 4001:
        http_status = 401
    elif exc.code == 4003:
        http_status = 403
    elif exc.code == 4004:
        http_status = 404
    elif exc.code >= 5000:
        http_status = 500
    return JSONResponse(
        status_code=http_status,
        content={"code": exc.code, "message": exc.message, "data": exc.data},
    )


# ── 健康检查 ──
@app.get("/health")
async def health_check() -> dict[str, str]:
    """健康检查端点."""
    return {"status": "ok"}


# ── 路由注册 ──
app.include_router(auth.router, prefix=f"{settings.api_prefix}/auth", tags=["认证"])
app.include_router(projects.router, prefix=f"{settings.api_prefix}/projects", tags=["项目"])
app.include_router(documents.router, prefix=f"{settings.api_prefix}/projects", tags=["文档"])
app.include_router(requirements.router, prefix=f"{settings.api_prefix}/projects", tags=["技术需求"])
app.include_router(workflow.router, prefix=f"{settings.api_prefix}/projects", tags=["工作流"])
app.include_router(division.router, prefix=f"{settings.api_prefix}/projects", tags=["分工协作"])
app.include_router(annotations.router, prefix=f"{settings.api_prefix}/projects", tags=["章节批注"])
app.include_router(benchmark.router, prefix=f"{settings.api_prefix}/projects", tags=["评分对标"])
app.include_router(workbench.router, prefix=f"{settings.api_prefix}/workbench", tags=["工作台"])
app.include_router(versions.router, prefix=f"{settings.api_prefix}/projects", tags=["版本库"])
app.include_router(kb.router, prefix=f"{settings.api_prefix}/kb", tags=["资料库"])
app.include_router(kb_bases.router, prefix=f"{settings.api_prefix}", tags=["知识库"])
app.include_router(users.router, prefix=f"{settings.api_prefix}", tags=["用户管理"])
app.include_router(audit.router, prefix=f"{settings.api_prefix}", tags=["审计日志"])
app.include_router(settings_api.router, prefix=f"{settings.api_prefix}/settings", tags=["系统设置"])
app.include_router(websocket.router)
