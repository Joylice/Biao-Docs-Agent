"""应用配置 — Pydantic Settings，环境变量前缀 BID_."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置，通过 BID_ 前缀环境变量注入."""

    model_config = SettingsConfigDict(
        env_prefix="BID_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── 应用 ──
    app_name: str = "投标软件技术方案智能体"
    debug: bool = False
    api_prefix: str = "/api/v1"

    # ── 数据库 ──
    database_url: str = "postgresql+psycopg://bid:bid@localhost:5432/bid"

    # ── Redis ──
    redis_url: str = "redis://localhost:6379/0"

    # ── JWT ──
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_expire_minutes: int = 120  # 2h
    jwt_refresh_expire_days: int = 7

    # ── MinIO ──
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "bid-documents"
    minio_secure: bool = False

    # ── LLM ──
    llm_mock: bool = False  # 测试模式：mock LLM 调用
    llm_model: str = "deepseek/deepseek-chat"
    llm_primary: str = "deepseek/deepseek-chat"
    llm_backup: str = "qwen/qwen-plus"

    # ── Embedding ──
    embedding_model: str = "bge-m3"
    embedding_dimension: int = 1024
    embedding_api_base: str = "http://localhost:11434/v1"

    # ── 上传限制 ──
    max_upload_size_mb: int = 50
    allowed_upload_types: list[str] = [
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "image/jpeg",
        "image/png",
    ]


settings = Settings()
