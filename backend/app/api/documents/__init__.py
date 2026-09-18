"""文档管理 API 路由包 — 按资源域拆分自 api/documents.py（第一轮-2 路由薄化）.

子模块：
- ``files``：文档/图片上传下载、列表、删除、重新解析（存储编排）
- ``format_requirements`` / ``disqualification``：提取结果人工编辑
- ``score_points``：评分点/技术需求查询
- ``kb``：资料库相似度检索

对外保持 ``from app.api import documents`` + ``documents.router`` 完全兼容
（main.py 以 ``app.include_router(documents.router, ...)`` 注册）。
"""

from fastapi import APIRouter

from . import disqualification, files, format_requirements, glossary, kb, score_points

router = APIRouter()
router.include_router(files.router)
router.include_router(format_requirements.router)
router.include_router(disqualification.router)
router.include_router(glossary.router)
router.include_router(kb.router)
router.include_router(score_points.router)

__all__ = ["router"]
