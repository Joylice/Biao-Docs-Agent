"""对象存储服务测试（MinIO 公共端点 host 重写）."""

import pytest

from app.core.config import settings
from app.services.document import storage_service


def test_presigned_url_rewrites_host_to_public_endpoint(monkeypatch) -> None:
    """presigned URL host 重写为公共端点（容器内网地址浏览器不可达）."""

    class _FakeClient:
        def presigned_get_object(self, bucket, key, expires):
            assert bucket == settings.minio_bucket
            assert key == "images/pid1/uuid/shot.png"
            return (
                "http://minio:9000/bid-documents/images/pid1/uuid/shot.png"
                "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=abc"
            )

    monkeypatch.setattr(storage_service, "_get_client", lambda: _FakeClient())
    monkeypatch.setattr(settings, "minio_public_endpoint", "localhost:9000")

    url = storage_service.presigned_url("images/pid1/uuid/shot.png")
    assert url.startswith("http://localhost:9000/bid-documents/images/pid1/uuid/shot.png?")
    assert "minio:9000" not in url
    # 查询参数（签名）保留
    assert "X-Amz-Signature=abc" in url


def test_presigned_url_keeps_host_when_public_endpoint_unset(monkeypatch) -> None:
    """未配置公共端点时保持原始 host（回退行为不变）."""

    class _FakeClient:
        def presigned_get_object(self, bucket, key, expires):
            return "http://minio:9000/bid-documents/k?sig=1"

    monkeypatch.setattr(storage_service, "_get_client", lambda: _FakeClient())
    monkeypatch.setattr(settings, "minio_public_endpoint", "")

    url = storage_service.presigned_url("k")
    assert url == "http://minio:9000/bid-documents/k?sig=1"


def test_download_file_returns_bytes(monkeypatch) -> None:
    """download_file 返回对象字节内容（代理端点依赖）."""

    class _FakeResponse:
        def read(self) -> bytes:
            return b"binary-data"

        def close(self) -> None:
            pass

        def release_conn(self) -> None:
            pass

    class _FakeClient:
        def get_object(self, bucket, key):
            return _FakeResponse()

    monkeypatch.setattr(storage_service, "_get_client", lambda: _FakeClient())
    assert storage_service.download_file("some/key.pdf") == b"binary-data"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
