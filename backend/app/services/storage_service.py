"""MinIO 对象存储服务."""

import io
import uuid
from datetime import timedelta
from typing import BinaryIO
from urllib.parse import urlsplit, urlunsplit

from minio import Minio
from minio.error import S3Error

from app.core.config import settings
from app.core.exceptions import BizError


def _get_client() -> Minio:
    """获取 MinIO 客户端."""
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


def ensure_bucket() -> None:
    """确保 bucket 存在."""
    client = _get_client()
    if not client.bucket_exists(settings.minio_bucket):
        client.make_bucket(settings.minio_bucket)


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

    配置了 minio_public_endpoint 时将 host 重写为公共端点：
    容器内 endpoint（如 minio:9000）是 Docker 内网地址，浏览器无法解析，
    导致图片预览失败/文件不可下载。
    """
    client = _get_client()
    try:
        url = client.presigned_get_object(
            settings.minio_bucket, storage_key, expires=timedelta(days=expires_days)
        )
    except S3Error as e:
        raise BizError(code=5003, message=f"签名地址生成失败: {e}") from None
    if settings.minio_public_endpoint:
        parts = urlsplit(url)
        url = urlunsplit(
            (parts.scheme, settings.minio_public_endpoint, parts.path, parts.query, parts.fragment)
        )
    return url


def delete_file(storage_key: str) -> None:
    """删除 MinIO 中的文件."""
    client = _get_client()
    try:
        client.remove_object(settings.minio_bucket, storage_key)
    except S3Error as e:
        raise BizError(code=5004, message=f"文件删除失败: {e}") from None
