"""MinIO 对象存储服务.

客户端采用模块级单例：首次调用时创建，后续复用，避免每次操作都新建连接。
lifespan 启动时调用 init_minio() 完成预创建 + bucket 初始化。
"""

import io
import logging
import uuid
from datetime import timedelta
from typing import BinaryIO

from minio import Minio
from minio.error import S3Error

from app.core.config import settings
from app.core.exceptions import BizError

logger = logging.getLogger(__name__)

# ── 模块级单例 ──
_client: Minio | None = None
_public_client: Minio | None = None


def init_minio() -> None:
    """初始化 MinIO 客户端单例 + 确保 bucket 存在.

    在 FastAPI lifespan 启动时调用。重复调用安全（幂等）。
    注意：minio-py 的 Minio(endpoint) 仅接受 host[:port]（不含 scheme/path），
    协议由 secure 参数决定；勿对 endpoint 追加 http(s):// 前缀。
    """
    global _client
    if _client is not None:
        return
    _client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    # 确保 bucket 存在（连接失败/权限不足不阻断启动——storage 操作首次调用时报错）
    try:
        if not _client.bucket_exists(settings.minio_bucket):
            _client.make_bucket(settings.minio_bucket)
            logger.info("MinIO bucket created: %s", settings.minio_bucket)
    except Exception as e:  # 涵盖 S3Error/连接失败/超时，均不阻断启动
        logger.error("MinIO bucket init failed (non-fatal): %s", e)


def _get_client() -> Minio:
    """获取 MinIO 客户端单例（内部网络 endpoint，上传/下载用）.

    若 init_minio() 未被调用（如测试环境），此处延迟初始化。
    """
    global _client
    if _client is None:
        init_minio()
    assert _client is not None
    return _client


def _get_public_client() -> Minio | None:
    """获取公共端点签名客户端（浏览器可达 host 直签，避免 host 替换导致签名失配）.

    minio_public_endpoint 为空时返回 None（调用方回退内部 client）。
    endpoint 为 host[:port]（如 192.168.18.200:19000），协议由 secure 决定。
    """
    global _public_client
    if not settings.minio_public_endpoint:
        return None
    if _public_client is None:
        _public_client = Minio(
            settings.minio_public_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
    return _public_client


def upload_file(
    file_content: BinaryIO,
    filename: str,
    content_type: str = "application/octet-stream",
    project_id: uuid.UUID | None = None,
    key_prefix: str | None = None,
) -> str:
    """上传文件到 MinIO，返回 storage_key.

    key_prefix 优先（如图片 images/{project_id}），否则按 project_id/global 分目录。
    """
    client = _get_client()
    # 生成唯一 key: {prefix}/{uuid}/{filename}
    prefix = key_prefix or (str(project_id) if project_id else "global")
    storage_key = f"{prefix}/{uuid.uuid4()}/{filename}"

    try:
        # 读取内容以获取大小
        data = file_content.read()
        file_size = len(data)
        data_stream = io.BytesIO(data)

        client.put_object(
            settings.minio_bucket,
            storage_key,
            data_stream,
            file_size,
            content_type=content_type,
        )
    except S3Error as e:
        raise BizError(code=5002, message=f"文件上传失败: {e}") from None

    return storage_key


def download_file(storage_key: str) -> bytes:
    """从 MinIO 下载文件，返回字节内容."""
    client = _get_client()
    response = None
    try:
        response = client.get_object(settings.minio_bucket, storage_key)
        return response.read()
    except S3Error as e:
        raise BizError(code=5003, message=f"文件下载失败: {e}") from None
    finally:
        # get_object 失败时 response 未赋值，直接 close 会 UnboundLocalError 掩盖原始异常
        if response is not None:
            response.close()
            response.release_conn()


def presigned_url(storage_key: str, expires_days: int = 7) -> str:
    """生成签名下载 URL（浏览器/Markdown 直读，无需鉴权头）.

    AWS SigV4 签名包含请求 host——若用容器内 endpoint（minio:9000）生成签名后再
    把 host 字符串替换为公共端点，浏览器按公共 host 请求时 MinIO 重新计算签名必然
    失配（SignatureDoesNotMatch，HTTP 403）。因此：
    - 配置了 minio_public_endpoint 时，直接用公共端点的 client 签名（host 即公共地址）；
    - 未配置（本地 dev endpoint 本身浏览器可达）时回退内部 client，保持原样返回。
    """
    client = _get_public_client() or _get_client()
    try:
        return client.presigned_get_object(
            settings.minio_bucket, storage_key, expires=timedelta(days=expires_days)
        )
    except S3Error as e:
        raise BizError(code=5003, message=f"签名地址生成失败: {e}") from None


def delete_file(storage_key: str) -> None:
    """删除 MinIO 中的文件."""
    client = _get_client()
    try:
        client.remove_object(settings.minio_bucket, storage_key)
    except S3Error as e:
        raise BizError(code=5004, message=f"文件删除失败: {e}") from None
