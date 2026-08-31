"""启动期密钥防护测试（P0-1.3）.

生产模式（debug=False 且 llm_mock=False）下默认密钥 → 拒绝启动；
开发/测试模式仅告警不阻塞。
"""

import logging

import pytest

from app.core.config import Settings, validate_runtime_secrets

DEFAULT_JWT = "change-me-in-production"
DEFAULT_MINIO = "minioadmin"


def _prod_settings(**overrides) -> Settings:
    """生产形态配置：debug=False 且 llm_mock=False."""
    base = {"debug": False, "llm_mock": False}
    base.update(overrides)
    return Settings(**base)


class TestValidateRuntimeSecrets:
    def test_production_default_jwt_rejected(self) -> None:
        """生产模式 + 默认 jwt_secret → 拒绝启动."""
        s = _prod_settings(minio_secret_key="real-secret")
        with pytest.raises(RuntimeError, match="BID_JWT_SECRET"):
            validate_runtime_secrets(s)

    def test_production_default_minio_rejected(self) -> None:
        """生产模式 + 默认 minio_secret_key → 拒绝启动."""
        s = _prod_settings(jwt_secret="real-secret")
        with pytest.raises(RuntimeError, match="BID_MINIO_SECRET_KEY"):
            validate_runtime_secrets(s)

    def test_production_custom_secrets_pass(self) -> None:
        """生产模式 + 双密钥均已自定义 → 放行."""
        s = _prod_settings(jwt_secret="real-secret", minio_secret_key="real-secret")
        validate_runtime_secrets(s)  # 不抛即通过

    def test_debug_mode_only_warns(self, caplog) -> None:
        """开发模式（debug=True）默认密钥 → 仅告警不阻塞."""
        s = _prod_settings(debug=True)
        with caplog.at_level(logging.WARNING):
            validate_runtime_secrets(s)

    def test_llm_mock_mode_only_warns(self, caplog) -> None:
        """mock 模式（llm_mock=True）默认密钥 → 仅告警不阻塞（测试/演示环境）."""
        s = _prod_settings(llm_mock=True)
        with caplog.at_level(logging.WARNING):
            validate_runtime_secrets(s)
