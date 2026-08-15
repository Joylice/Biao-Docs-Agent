"""FastAPI 应用入口."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import auth, documents, projects, websocket, workflow
from app.core.config import settings
from app.core.exceptions import BizError


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期：启动/关闭时的资源管理."""
    # TODO: 初始化 MinIO 客户端、Redis 连接池等
    yield
    # TODO: 清理资源


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

# ── CORS ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
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
app.include_router(workflow.router, prefix=f"{settings.api_prefix}/projects", tags=["工作流"])
app.include_router(websocket.router)
