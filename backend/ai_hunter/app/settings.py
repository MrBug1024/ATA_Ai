from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]

# These names belong to the legacy projects and must never be selected by the
# annual-audit service.  The active database name is supplied by backend/.env.
ANNUAL_AUDIT_LEGACY_MYSQL_DATABASES = frozenset(
    {
        "ata_agent",
        "ai_hunter",
        "cpwsdata",
        "npa",
        "npa_lang",
        "bad_assets",
    }
)
ANNUAL_AUDIT_LEGACY_POSTGRES_DATABASES = frozenset(
    {
        "ai_hunter",
        "npa",
        "npa_lang",
        "bad_assets",
        "cpwsdata",
    }
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Runtime configuration lives in backend/.env.  The local Docker
        # stack is imported by scripts/annual-audit-local.ps1 into the process
        # environment, so its .env.local must not override online settings.
        env_file=(BACKEND_DIR / ".env",),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8080
    log_level: str = "INFO"
    cors_allow_origins: str = "*"
    cors_allow_credentials: bool = False
    cors_allow_methods: str = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
    cors_allow_headers: str = "*"
    log_include_request_fields: bool = True
    log_payload_preview_chars: int = 240
    log_dir: str = "logs"
    log_app_file_name: str = "app.log"
    log_access_file_name: str = "access.log"
    log_file_backup_count: int = 30

    llm_default_provider: str = "minimax"
    llm_provider_router: str | None = None
    llm_provider_report_a: str | None = None
    llm_provider_report_b: str | None = None
    llm_provider_agent: str | None = None
    router_execution_mode: str = "legacy"

    # This service has one business domain and one HTTP entrypoint.
    business_domain: str = "annual_audit"
    platform_project_code: str = "ata_ai"

    # Annual-audit storage credentials are supplied by the deployment env.
    annual_mysql_host: str = Field(
        "127.0.0.1",
        validation_alias=AliasChoices("ANNUAL_MYSQL_HOST", "MYSQL_HOST"),
    )
    annual_mysql_port: int = Field(
        3306,
        validation_alias=AliasChoices("ANNUAL_MYSQL_PORT", "MYSQL_PORT"),
    )
    annual_mysql_user: str = Field(
        "root",
        validation_alias=AliasChoices("ANNUAL_MYSQL_USER", "MYSQL_USER"),
    )
    annual_mysql_password: str = Field(
        "",
        validation_alias=AliasChoices("ANNUAL_MYSQL_PASSWORD", "MYSQL_PASSWORD"),
    )
    annual_mysql_database: str = Field(
        "",
        validation_alias=AliasChoices("ANNUAL_MYSQL_DATABASE", "MYSQL_DATABASE"),
    )
    annual_mysql_connect_timeout_seconds: int = 10
    annual_redis_host: str = Field(
        "127.0.0.1",
        validation_alias=AliasChoices("ANNUAL_REDIS_HOST", "REDIS_HOST"),
    )
    annual_redis_namespace: str = Field(
        "ata:dev:",
        validation_alias=AliasChoices("ANNUAL_REDIS_NAMESPACE", "REDIS_NAMESPACE"),
    )
    annual_postgres_host: str = Field(
        "127.0.0.1",
        validation_alias=AliasChoices("ANNUAL_POSTGRES_HOST", "POSTGRES_HOST"),
    )
    annual_postgres_dsn: str = Field(
        "",
        validation_alias=AliasChoices("ANNUAL_POSTGRES_DSN", "POSTGRES_DSN"),
    )
    annual_postgres_port: int = Field(
        55432,
        validation_alias=AliasChoices("ANNUAL_POSTGRES_PORT", "POSTGRES_PORT"),
    )
    annual_postgres_database: str = Field(
        "ata_agent_platform",
        validation_alias=AliasChoices("ANNUAL_POSTGRES_DATABASE", "POSTGRES_DATABASE"),
    )
    annual_postgres_user: str = Field(
        "ata_agent_app",
        validation_alias=AliasChoices("ANNUAL_POSTGRES_USER", "POSTGRES_USER"),
    )
    annual_postgres_password: str = Field(
        "",
        validation_alias=AliasChoices("ANNUAL_POSTGRES_PASSWORD", "POSTGRES_PASSWORD"),
    )
    annual_redis_port: int = Field(
        56379,
        validation_alias=AliasChoices("ANNUAL_REDIS_PORT", "REDIS_PORT"),
    )
    annual_redis_password: str = Field(
        "",
        validation_alias=AliasChoices("ANNUAL_REDIS_PASSWORD", "REDIS_PASSWORD"),
    )
    annual_minio_endpoint: str = Field(
        "",
        validation_alias=AliasChoices("ANNUAL_MINIO_ENDPOINT", "AI_HUNTER_MINIO_ENDPOINT"),
    )
    annual_minio_enabled: bool = Field(
        True,
        validation_alias=AliasChoices("ANNUAL_MINIO_ENABLED", "AI_HUNTER_MINIO_ENABLED"),
    )
    annual_minio_use_ssl: bool = Field(
        False,
        validation_alias=AliasChoices("ANNUAL_MINIO_USE_SSL", "AI_HUNTER_MINIO_USE_SSL"),
    )
    annual_minio_api_port: int = Field(
        61000,
        validation_alias=AliasChoices("ANNUAL_MINIO_API_PORT", "MINIO_API_PORT"),
    )
    annual_minio_access_key: str = Field(
        "ata_annual_local",
        validation_alias=AliasChoices("ANNUAL_MINIO_ACCESS_KEY", "AI_HUNTER_MINIO_ACCESS_KEY"),
    )
    annual_minio_secret_key: str = Field(
        "",
        validation_alias=AliasChoices("ANNUAL_MINIO_SECRET_KEY", "AI_HUNTER_MINIO_SECRET_KEY"),
    )
    annual_minio_bucket_raw: str = Field(
        "ata-annual-raw",
        validation_alias=AliasChoices("ANNUAL_MINIO_BUCKET_RAW", "AI_HUNTER_MINIO_BUCKET_RAW"),
    )
    annual_minio_bucket_derived: str = Field(
        "ata-annual-derived",
        validation_alias=AliasChoices("ANNUAL_MINIO_BUCKET_DERIVED", "AI_HUNTER_MINIO_BUCKET_DERIVED"),
    )
    annual_minio_bucket_artifacts: str = Field(
        "ata-annual-artifacts",
        validation_alias=AliasChoices("ANNUAL_MINIO_BUCKET_ARTIFACTS", "AI_HUNTER_MINIO_BUCKET_ARTIFACTS"),
    )
    annual_minio_prefix: str = "annual_audit"
    annual_vector_collection_prefix: str = "ata_annual_audit"
    annual_embedding_model: str = ""
    annual_embedding_dimension: int = 1024
    annual_auth_local_jwt_secret: str = Field(
        "",
        validation_alias=AliasChoices("ANNUAL_AUTH_LOCAL_JWT_SECRET", "AUTH_LOCAL_JWT_SECRET"),
    )

    openai_api_key: str = ""
    openai_base_url: str | None = ""
    openai_model_router: str = "gpt-4.1-mini"
    openai_model_report_a: str = "gpt-4.1"
    openai_model_report_b: str = "gpt-4.1"
    openai_model_agent: str = "gpt-4.1"
    openai_temperature_router: float = 0.1
    openai_temperature_report: float = 0.7
    openai_temperature_agent: float = 0.3

    langgraph_checkpointer: str = "memory"
    langgraph_checkpointer_auto_setup: bool = False
    langgraph_thread_ttl_hours: int = 168
    langgraph_memory_window: int = 12
    langgraph_memory_max_tokens: int = 1200
    langgraph_memory_summary_chars: int = 1200

    # 权限网关（Tier 3）：认证信任用户中心 JWT / 私有化本地身份，授权本项目自管。
    auth_enabled: bool = False                 # false=放行(全权限)，true=强制鉴权
    auth_identity_mode: str = "private"        # private=私有化本地身份；platform=平台用户中心
    user_center_jwt_alg: str = "HS256"         # HS256(手验) / RS256(PyJWT)
    user_center_jwt_secret: str = ""           # HS256 密钥（与用户中心约定）
    user_center_jwt_public_key: str = ""       # RS256 公钥(PEM)
    auth_dev_trust_headers: bool = True        # 无有效 JWT 时是否信任 X-User-* 开发头
    auth_jwt_user_claim: str = "sub"           # JWT 中用户 id 的 claim 名
    auth_jwt_name_claim: str = "name"
    auth_jwt_roles_claim: str = "roles"
    auth_jwt_company_claim: str = "company"
    auth_jwt_apps_claim: str = "apps"
    auth_require_project_access: bool = False
    auth_project_code: str = "ai_hunter"
    auth_legacy_roles_enabled: bool = False     # v2 迁移期允许 JWT/dev header roles 回退
    auth_local_jwt_secret: str = ""             # private 模式本地登录 JWT HS256 密钥；为空回退 USER_CENTER_JWT_SECRET
    auth_local_access_token_minutes: int = 480
    auth_password_hash_algo: str = "argon2id"
    auth_password_min_length: int = 10
    auth_password_failed_lock_threshold: int = 5
    auth_password_lock_minutes: int = 15
    auth_role_permissions: str = ""            # 角色→权限映射 JSON 覆盖（空则用代码默认）
    heavy_payload_ttl_seconds: int = 86400
    heavy_payload_enable_postgres: bool = True
    heavy_payload_prune_batch_size: int = 500

    redis_url: str | None = None
    ai_hunter_minio_enabled: bool = False
    ai_hunter_minio_endpoint: str = ""
    ai_hunter_minio_access_key: str = ""
    ai_hunter_minio_secret_key: str = ""
    ai_hunter_minio_bucket_raw: str = ""
    ai_hunter_minio_bucket_derived: str = ""
    ai_hunter_minio_bucket_artifacts: str = ""
    ai_hunter_minio_use_ssl: bool = True

    ocr_base_url: str = "https://ocr.rhzy.ai"
    ocr_api_key: str = ""
    ocr_timeout_seconds: int = 600
    ocr_verify_ssl: bool = False
    ocr_backend: str = "vlm-auto-engine"
    ocr_lang_list: str = "ch"
    ocr_table_enable_pdf: bool = True
    ocr_table_enable_image: bool = False
    ocr_auto_rotate_pdf: bool = False
    ocr_auto_rotate_image: bool = True
    ocr_pdf_split_enabled: bool = False
    ocr_pdf_split_threshold_mb: int = 10
    ocr_pdf_split_threshold_pages: int = 10
    ocr_pdf_chunk_max_mb: int = 8
    ocr_pdf_chunk_max_pages: int = 1
    ocr_pdf_chunk_concurrency: int = 1
    ocr_pdf_chunk_timeout_seconds: int = 300
    ocr_pdf_chunk_max_retries: int = 2

    faker_model_base_url: str = "https://faker-model.rhzy.ai/v1"
    faker_model_api_key: str = ""
    faker_model_router: str = "vllm/google/gemma-4-26B-A4B-it"
    faker_model_report_a: str = "vllm/google/gemma-4-26B-A4B-it"
    faker_model_report_b: str = "vllm/google/gemma-4-26B-A4B-it"
    faker_model_agent: str = "vllm/google/gemma-4-26B-A4B-it"

    kimi_base_url: str = "https://api.moonshot.cn/v1"
    kimi_api_key: str = ""
    kimi_model_router: str = "kimi/Kimi-k2.6"
    kimi_model_report_a: str = "kimi/Kimi-k2.6"
    kimi_model_report_b: str = "kimi/Kimi-k2.6"
    kimi_model_agent: str = "kimi/Kimi-k2.6"

    minimax_base_url: str = "https://api.minimaxi.com/v1"
    minimax_api_key: str = ""
    minimax_model_router: str = "MiniMax-M2.7"
    minimax_model_report_a: str = "MiniMax-M2.7"
    minimax_model_report_b: str = "MiniMax-M2.7"
    minimax_model_agent: str = "MiniMax-M2.7"

    max_upload_files: int = 20
    max_upload_file_mb: int = 500
    max_image_file_mb: int = 10
    max_file_batch_count: int = 5
    ocr_max_parallel: int = 5

    # 报告生成后是否自动将抽取出的年度审计任务写入本地任务表。
    enable_task_autocreate: bool = True
    enable_agent_memory: bool = True
    enable_report_cache: bool = True
    enable_reasoning_trace: bool = False
    agent_recursion_limit: int = 8
    report_section_max_completion_tokens_kimi: int = 12288
    report_section_provider_1: str = ""
    report_section_provider_2: str = ""
    report_section_provider_3: str = ""
    report_section_provider_4: str = ""
    report_section_provider_5: str = ""
    report_section_provider_6: str = ""
    report_section_provider_7: str = ""
    report_section_provider_8: str = ""
    report_section_timeout_seconds: int = 300
    report_section_concurrency: int = 3
    report_section_concurrency_kimi: int = 3
    report_section_concurrency_minimax: int = 3
    audit_api_base_url: str = ""
    audit_api_timeout_seconds: int = 600
    audit_api_token: str = ""
    task_api_base_url: str = ""
    case_api_base_url: str = ""
    knowledge_api_base_url: str = ""
    enterprise_api_base_url: str = ""
    doc_category_api_base_url: str = ""
    metrics_amount_decimals: str = ""
    metrics_currency: str = ""
    metrics_materiality_ruleset_version: str = ""
    metrics_sampling_ruleset_version: str = ""
    metrics_confirmation_ruleset_version: str = ""
    deadline_red_days: str = ""
    deadline_yellow_days: str = ""
    enable_doc_category_api_mock: bool = False

    @model_validator(mode="after")
    def _guard_annual_audit_database(self):
        """Build the isolated local annual-audit storage contract."""

        self.business_domain = "annual_audit"
        self.app_port = 8080
        if self.platform_project_code.strip().lower() in {"ai_hunter", "npa", "npa_lang", "bad_assets"}:
            raise ValueError("annual audit refuses a legacy project code")
        if not self.platform_project_code.strip():
            raise ValueError("annual audit requires PLATFORM_PROJECT_CODE")
        self.auth_project_code = "annual_audit"
        database = self.annual_mysql_database.strip().lower()
        if not database:
            raise ValueError(
                "annual audit requires MYSQL_DATABASE/ANNUAL_MYSQL_DATABASE"
            )
        if database in ANNUAL_AUDIT_LEGACY_MYSQL_DATABASES:
            raise ValueError(
                "annual audit refuses legacy MySQL database "
                f"{self.annual_mysql_database!r}; configure the new project's empty database"
            )
        postgres_database = self.annual_postgres_database.strip().lower()
        if postgres_database in ANNUAL_AUDIT_LEGACY_POSTGRES_DATABASES:
            raise ValueError(
                "annual audit refuses legacy PostgreSQL database "
                f"{self.annual_postgres_database!r}; configure the new project's platform database"
            )

        if not self.annual_postgres_dsn.strip():
            password = self.annual_postgres_password
            self.annual_postgres_dsn = (
                f"postgresql+psycopg://{self.annual_postgres_user}:{password}"
                f"@{self.annual_postgres_host}:{self.annual_postgres_port}/{self.annual_postgres_database}"
            )

        if self.annual_redis_password:
            self.redis_url = (
                f"redis://:{self.annual_redis_password}@{self.annual_redis_host}:"
                f"{self.annual_redis_port}/0"
            )
        elif self.redis_url:
            self.redis_url = self.redis_url.strip()
            if "://" not in self.redis_url:
                self.redis_url = (
                    f"redis://{self.redis_url}:{self.annual_redis_port}/0"
                )
        else:
            self.redis_url = None

        self.ai_hunter_minio_enabled = bool(self.annual_minio_enabled)
        self.ai_hunter_minio_endpoint = (
            self.annual_minio_endpoint.strip()
            or f"127.0.0.1:{self.annual_minio_api_port}"
        )
        self.ai_hunter_minio_access_key = self.annual_minio_access_key
        self.ai_hunter_minio_secret_key = self.annual_minio_secret_key
        self.ai_hunter_minio_bucket_raw = self.annual_minio_bucket_raw
        self.ai_hunter_minio_bucket_derived = self.annual_minio_bucket_derived
        self.ai_hunter_minio_bucket_artifacts = self.annual_minio_bucket_artifacts
        self.ai_hunter_minio_use_ssl = self.annual_minio_use_ssl
        if self.annual_auth_local_jwt_secret:
            self.auth_local_jwt_secret = self.annual_auth_local_jwt_secret
            self.user_center_jwt_secret = self.annual_auth_local_jwt_secret

        namespace = self.annual_redis_namespace.strip()
        if self.redis_url and (
            not namespace.startswith("ata:") or not namespace.endswith(":")
        ):
            raise ValueError("annual audit Redis requires ANNUAL_REDIS_NAMESPACE=ata:<name>:")
        return self

    def resolve_provider(self, role: str) -> str:
        """Resolve which provider should serve a graph role."""
        overrides = {
            "router": self.llm_provider_router,
            "report_a": self.llm_provider_report_a,
            "report_b": self.llm_provider_report_b,
            "agent": self.llm_provider_agent,
        }
        return (overrides.get(role) or self.llm_default_provider).strip().lower()

    def get_llm_config(self, role: str, provider_override: str | None = None) -> dict[str, str]:
        """Return the OpenAI-compatible config tuple for the given role.

        provider_override 允许按段分流（如核心段走 kimi、其余 minimax），
        其余字段仍取该 provider 在该 role 下的 key/base_url/model。
        """
        provider = (provider_override or self.resolve_provider(role)).strip().lower()
        if provider == "minimax":
            return {
                "provider": provider,
                "api_key": self.minimax_api_key,
                "base_url": self.minimax_base_url,
                "model": getattr(self, f"minimax_model_{role}"),
            }
        if provider == "kimi":
            return {
                "provider": provider,
                "api_key": self.kimi_api_key,
                "base_url": self.kimi_base_url,
                "model": getattr(self, f"kimi_model_{role}"),
            }
        if provider == "faker":
            return {
                "provider": provider,
                "api_key": self.faker_model_api_key,
                "base_url": self.faker_model_base_url,
                "model": getattr(self, f"faker_model_{role}"),
            }
        if provider == "openai":
            return {
                "provider": provider,
                "api_key": self.openai_api_key,
                "base_url": self.openai_base_url,
                "model": getattr(self, f"openai_model_{role}"),
            }
        raise ValueError(f"Unsupported llm provider: {provider}")

    @property
    def postgres_checkpointer_dsn(self) -> str:
        """Resolve the platform PostgreSQL DSN without cross-project fallback."""

        dsn = self.annual_postgres_dsn.strip()
        if not dsn:
            raise RuntimeError("annual audit requires an isolated PostgreSQL DSN")
        if dsn.startswith("postgresql+psycopg://"):
            return dsn.replace("postgresql+psycopg://", "postgresql://", 1)
        return dsn

    @property
    def cors_allow_origins_list(self) -> list[str]:
        """Parse comma-separated CORS origins into a normalized list."""
        values = [item.strip() for item in self.cors_allow_origins.split(",")]
        return [item for item in values if item]

    @property
    def cors_allow_methods_list(self) -> list[str]:
        """Parse comma-separated CORS methods into a normalized list."""
        values = [item.strip().upper() for item in self.cors_allow_methods.split(",")]
        return [item for item in values if item]

    @property
    def cors_allow_headers_list(self) -> list[str]:
        """Parse comma-separated CORS headers into a normalized list."""
        values = [item.strip() for item in self.cors_allow_headers.split(",")]
        return [item for item in values if item]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
