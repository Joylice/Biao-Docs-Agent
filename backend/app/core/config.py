"""应用配置 — Pydantic Settings，环境变量前缀 BID_."""

import logging

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

DEFAULT_JWT_SECRET = "change-me-in-production"
DEFAULT_MINIO_SECRET_KEY = "minioadmin"


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
    # CORS 允许的前端来源（逗号分隔的环境变量，如 "http://localhost:5173,http://localhost:3000"）
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # ── 数据库 ──
    database_url: str = "postgresql+psycopg://bid:bid@localhost:5432/bid"
    workflow_pool_timeout: float = 30.0  # checkpointer 连接池等待超时（秒）

    # ── Redis ──
    redis_url: str = "redis://localhost:6379/0"

    # ── JWT ──
    jwt_secret: str = DEFAULT_JWT_SECRET
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
    # 浏览器可达的公共端点（presigned URL host 重写）；空 = 不重写。
    # 容器内 BID_MINIO_ENDPOINT=minio:9000 是 Docker 内网地址，浏览器无法解析。
    minio_public_endpoint: str = ""
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = DEFAULT_MINIO_SECRET_KEY
    minio_bucket: str = "bid-documents"
    minio_secure: bool = False

    # ── 导出（阶段 E4 封面）──
    company_name: str = ""  # 投标公司名（封面占位，可空）

    # ── LLM ──
    llm_mock: bool = False  # 测试模式：mock LLM 调用
    llm_model: str = "deepseek/deepseek-chat"
    llm_primary: str = "deepseek/deepseek-chat"
    llm_backup: str = "qwen/qwen-plus"
    # LLM 自定义端点（OpenAI 兼容），为空时使用模型默认端点
    llm_api_base: str = ""
    # LLM 自定义端点专用密钥（仅用于 llm_api_base，不回退云端密钥）
    llm_api_key: str = ""
    # 云端提供商 API Key（环境变量回退，数据库无配置时使用）
    deepseek_api_key: str = ""
    dashscope_api_key: str = ""
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    zhipu_api_key: str = ""
    moonshot_api_key: str = ""

    # ── Embedding ──
    # 默认 DashScope 云端 embedding；模型名必须携带 litellm provider 前缀
    # （如 dashscope/text-embedding-v3），否则报 "LLM Provider NOT provided"。
    # 本地 Ollama 等场景可用 BID_EMBEDDING_MODEL 覆盖（如 ollama/bge-m3）。
    embedding_model: str = "dashscope/text-embedding-v3"
    embedding_dimension: int = 1024
    embedding_api_base: str = "http://localhost:11434/v1"
    embedding_api_key: str = ""

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


def validate_runtime_secrets(s: Settings | None = None) -> None:
    """启动期密钥防护（P0）：生产模式默认密钥 → 拒绝启动.

    生产模式定义：debug=False 且 llm_mock=False（真实签名 + 真实 LLM 调用）。
    开发模式（debug=True）或 mock 模式下仅告警不阻塞，避免破坏本地/测试环境。
    """
    cfg = s if s is not None else settings
    insecure: list[str] = []
    if cfg.jwt_secret == DEFAULT_JWT_SECRET:
        insecure.append("BID_JWT_SECRET")
    if cfg.minio_secret_key == DEFAULT_MINIO_SECRET_KEY:
        insecure.append("BID_MINIO_SECRET_KEY")
    if not insecure:
        return
    if cfg.debug or cfg.llm_mock:
        logger.warning(
            "安全告警（仅开发/mock 模式放行）：以下密钥仍为默认值——%s；"
            "生产部署前必须设置自定义值",
            ", ".join(insecure),
        )
        return
    raise RuntimeError(
        f"拒绝启动：生产模式下默认密钥不安全（{', '.join(insecure)}）。"
        "请设置环境变量后重启"
    )
