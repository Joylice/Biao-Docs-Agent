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
    workflow_pool_timeout: float = 30.0  # checkpointer 连接池等待超时（秒）

    # ── Redis ──
    redis_url: str = "redis://localhost:6379/0"

    # ── JWT ──
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_expire_minutes: int = 120  # 2h
    jwt_refresh_expire_days: int = 7

    # ── 权限与安全 ──
    # 管理员用户邮箱列表（逗号分隔，项目唯一用户标识为 email）。仅列表内账号可
    # PUT /settings/llm 与 POST /settings/llm/test；为空时拒绝写入并提示配置（C-1）。
    admin_user_ids: str = ""
    # LLM 密钥落库加密（Fernet）的独立派生源；为空时回退 jwt_secret 派生并告警（W-2）。
    llm_crypto_secret: str = ""

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
    # 默认 DashScope 云端 embedding；模型名必须携带 litellm provider 前缀
    # （如 dashscope/text-embedding-v3），否则报 "LLM Provider NOT provided"。
    # 本地 Ollama 等场景可用 BID_EMBEDDING_MODEL 覆盖（如 ollama/bge-m3）。
    embedding_model: str = "dashscope/text-embedding-v3"
    embedding_dimension: int = 1024
    embedding_api_base: str = "http://localhost:11434/v1"

    # ── Rerank 精排（云端 API，DashScope gte-rerank 兼容协议）──
    # 默认关闭（opt-in）：未启用/未配置密钥/mock 模式下检索保持原向量序。
    # api_key 仅经环境变量注入，禁止写入日志与明文文档。
    rerank_enabled: bool = False
    rerank_api_base: str = (
        "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    )
    rerank_api_key: str = ""
    rerank_model: str = "gte-rerank"

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
