from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Runtime configuration lives only in backend/.env.
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

    # All application data is stored in the shared PostgreSQL service.
    database_backend: str = "postgresql"
    postgresql_host: str = "192.168.10.192"
    postgresql_port: int = 5432
    postgresql_database: str = "ata_ai"
    postgresql_admin_user: str = "postgres"
    postgresql_admin_password: str = "123456"

    # Redis is the only cache service. Do not add legacy aliases or URL inputs.
    redis_host: str = "192.168.11.118"
    redis_port: int = 6379
    redis_password: str = "root"
    redis_namespace: str = "ata:dev:"

    # Existing online MinIO keys remain the sole object-storage contract.
    annual_minio_enabled: bool = False
    annual_minio_endpoint: str = ""
    annual_minio_access_key: str = ""
    annual_minio_secret_key: str = ""
    annual_minio_bucket_raw: str = "ata-annual-raw"
    annual_minio_bucket_derived: str = "ata-annual-derived"
    annual_minio_bucket_artifacts: str = "ata-annual-artifacts"
    annual_minio_bucket_templates: str = "ata-document-templates"
    annual_minio_use_ssl: bool = True
    annual_minio_prefix: str = "annual_audit"
    attachment_template_max_mb: int = 50
    attachment_zip_max_entries: int = 2_000
    attachment_zip_max_uncompressed_mb: int = 250
    attachment_zip_max_entry_mb: int = 50
    attachment_zip_max_ratio: int = 100
    attachment_xml_max_mb: int = 20
    attachment_clamav_host: str = ""
    attachment_clamav_port: int = 3310
    attachment_clamav_timeout_seconds: int = 30
    attachment_clamav_required: bool = False
    attachment_gotenberg_url: str = ""
    attachment_gotenberg_timeout_seconds: int = 120
    attachment_preview_required: bool = False
    attachment_preview_max_mb: int = 200
    attachment_celery_broker_url: str = ""
    attachment_celery_queue: str = "annual-attachments"
    attachment_worker_eager: bool = False
    attachment_job_stale_seconds: int = 900
    attachment_ticket_ttl_seconds: int = 300
    attachment_renderer_image_digest: str = "local-unpinned"
    attachment_font_manifest_version: str = "local-unpinned"
    annual_vector_collection_prefix: str = "ata_annual_audit"
    annual_embedding_model: str = ""
    annual_embedding_dimension: int = 1024
    annual_auth_local_jwt_secret: str = ""

    openai_api_key: str = ""
    openai_base_url: str | None = ""
    openai_model_router: str = "gpt-4.1-mini"
    openai_model_report_a: str = "gpt-4.1"
    openai_model_report_b: str = "gpt-4.1"
    openai_model_agent: str = "gpt-4.1"
    openai_temperature_router: float = 0.1
    openai_temperature_report: float = 0.7
    openai_temperature_agent: float = 0.3

    langgraph_checkpointer: str = "postgres"
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
    def _validate_storage_contract(self):
        """Validate the shared external storage contract."""

        self.business_domain = "annual_audit"
        self.app_port = 8080
        if self.platform_project_code.strip().lower() in {"ai_hunter", "npa", "npa_lang", "bad_assets"}:
            raise ValueError("annual audit refuses a legacy project code")
        if not self.platform_project_code.strip():
            raise ValueError("annual audit requires PLATFORM_PROJECT_CODE")
        self.auth_project_code = "annual_audit"
        if self.database_backend.strip().lower() != "postgresql":
            raise ValueError("DATABASE_BACKEND must be postgresql")
        if self.langgraph_checkpointer.strip().lower() != "postgres":
            raise ValueError("LANGGRAPH_CHECKPOINTER must be postgres")
        self.langgraph_checkpointer = "postgres"
        if not self.postgresql_host.strip():
            raise ValueError("POSTGRESQL_HOST is required")
        if not self.postgresql_admin_user.strip():
            raise ValueError("POSTGRESQL_ADMIN_USER is required")
        if not self.redis_host.strip():
            raise ValueError("REDIS_HOST is required")
        if not self.redis_password.strip():
            raise ValueError("REDIS_PASSWORD is required")
        if not self.heavy_payload_enable_postgres:
            raise ValueError("HEAVY_PAYLOAD_ENABLE_POSTGRES must be true")
        namespace = self.redis_namespace.strip()
        if not namespace.startswith("ata:") or not namespace.endswith(":"):
            raise ValueError("REDIS_NAMESPACE must start with ata: and end with :")
        if self.annual_minio_enabled:
            required_minio_fields = {
                "ANNUAL_MINIO_ENDPOINT": self.annual_minio_endpoint,
                "ANNUAL_MINIO_ACCESS_KEY": self.annual_minio_access_key,
                "ANNUAL_MINIO_SECRET_KEY": self.annual_minio_secret_key,
                "ANNUAL_MINIO_BUCKET_RAW": self.annual_minio_bucket_raw,
                "ANNUAL_MINIO_BUCKET_DERIVED": self.annual_minio_bucket_derived,
                "ANNUAL_MINIO_BUCKET_ARTIFACTS": self.annual_minio_bucket_artifacts,
                "ANNUAL_MINIO_BUCKET_TEMPLATES": self.annual_minio_bucket_templates,
            }
            missing = [name for name, value in required_minio_fields.items() if not value.strip()]
            if missing:
                raise ValueError(f"enabled MinIO requires: {', '.join(missing)}")
        if not self.attachment_celery_broker_url.strip():
            self.attachment_celery_broker_url = self.redis_dsn
        if self.annual_auth_local_jwt_secret:
            self.auth_local_jwt_secret = self.annual_auth_local_jwt_secret
            self.user_center_jwt_secret = self.annual_auth_local_jwt_secret

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
        """Build the PostgreSQL DSN from the standardized environment fields."""

        database = self.postgresql_database.strip()
        if not database:
            raise RuntimeError("POSTGRESQL_DATABASE is required")
        user = quote(self.postgresql_admin_user, safe="")
        password = quote(self.postgresql_admin_password, safe="")
        return (
            f"postgresql://{user}:{password}@{self.postgresql_host}:"
            f"{self.postgresql_port}/{database}"
        )

    @property
    def redis_dsn(self) -> str:
        """Build the Redis DSN from the standardized environment fields."""

        password = quote(self.redis_password, safe="")
        credentials = f":{password}@" if password else ""
        return f"redis://{credentials}{self.redis_host}:{self.redis_port}/0"

    def require_runtime_storage(self) -> None:
        """Reject application startup without the external storage contract."""

        _ = self.postgres_checkpointer_dsn
        if not self.annual_minio_enabled:
            raise RuntimeError("ANNUAL_MINIO_ENABLED must be true for runtime file storage")

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
