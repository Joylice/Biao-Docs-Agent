"""MinIO 对象存储服务."""

import io
import uuid
from typing import BinaryIO

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
) -> str:
    """上传文件到 MinIO，返回 storage_key."""
    client = _get_client()
    # 生成唯一 key: project_id/uuid/filename
    prefix = str(project_id) if project_id else "global"
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
    try:
        response = client.get_object(settings.minio_bucket, storage_key)
        return response.read()
    except S3Error as e:
        raise BizError(code=5003, message=f"文件下载失败: {e}") from None
    finally:
        response.close()
        response.release_conn()


def delete_file(storage_key: str) -> None:
    """删除 MinIO 中的文件."""
    client = _get_client()
    try:
        client.remove_object(settings.minio_bucket, storage_key)
    except S3Error as e:
        raise BizError(code=5004, message=f"文件删除失败: {e}") from None
