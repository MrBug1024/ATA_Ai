from functools import lru_cache
from typing import Literal

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "dev"
    app_host: str = "0.0.0.0"
    app_port: int = 8081
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
    router_execution_mode: Literal["legacy", "business_line"] = "legacy"

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

    postgres_dsn: str = Field(
        default="postgresql+psycopg://user:password@127.0.0.1:5432/ai_hunter"
    )
    redis_url: str | None = None
    ai_hunter_minio_enabled: bool = False
    ai_hunter_minio_endpoint: str = ""
    ai_hunter_minio_access_key: str = ""
    ai_hunter_minio_secret_key: str = ""
    ai_hunter_minio_bucket_raw: str = ""
    ai_hunter_minio_bucket_derived: str = ""
    ai_hunter_minio_bucket_artifacts: str = ""
    ai_hunter_minio_use_ssl: bool = True

    # 单体服务内的领域 API 地址。旧的分服务变量保留为空值兼容项，
    # 未显式配置时全部回退到这一地址。
    unified_api_base_url: str = "http://127.0.0.1:8081"
    audit_api_base_url: str = ""
    audit_api_timeout_seconds: int = 600
    audit_api_token: str | None = None

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

    task_api_base_url: str = ""
    case_api_base_url: str = ""
    knowledge_api_base_url: str = ""
    enterprise_api_base_url: str = ""
    doc_category_api_base_url: str = ""
    cpws_db_host: str = "10.0.10.114"
    cpws_db_port: int = 5434
    cpws_db_user: str = "postgres"
    cpws_db_password: str = ""
    cpws_db_name: str = "cpwsdata"
    cpws_query_limit: int = 5
    cpws_qdrant_base_url: str | None = "http://10.0.10.2:6333"
    cpws_qdrant_collection: str = "case_chunks_000"
    cpws_qdrant_api_key: str = ""
    cpws_qdrant_timeout_seconds: int = 30
    cpws_embedding_base_url: str | None = None
    cpws_embedding_api_key: str = ""
    cpws_embedding_model: str = "embo-01"
    cpws_embedding_timeout_seconds: int = 30

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

    # 确定性数值引擎业务参数。JSON 型字段保持字符串形式，业务计算层统一解析。
    metrics_discount_rate: float = 0.12
    metrics_amount_decimals: int = 4
    metrics_tranche_years: str = '{"T1":0.125,"T2":0.875,"T3":1.5}'
    metrics_tranche_allocation: str = '{"T1":0.2,"T2":0.5,"T3":0.3}'
    metrics_tranche_weight: str = '{"T1":0.95,"T2":0.85,"T3":0.7}'
    metrics_zeroing_requires: str = '[["查封","案外异议"],["查封","强占"],["查封","物理抗辩"]]'

    # 回款闭环 / 进度看板提醒参数。
    recovery_overdue_days: int = 60
    profit_distribution_threshold_pct: float = 85.0
    deadline_red_days: int = 30
    deadline_yellow_days: int = 90

    # 完整审计/重审提取任务后是否自动写入任务 API；关闭时仍保留 extracted_tasks。
    enable_task_autocreate: bool = True
    enable_agent_memory: bool = True
    enable_report_cache: bool = True
    enable_reasoning_trace: bool = False
    enable_doc_category_api_mock: bool = False
    agent_recursion_limit: int = 8
    report_section_timeout_seconds: float = 150.0
    report_section_max_completion_tokens_kimi: int = 12288
    report_section_concurrency: int = 3
    report_section_concurrency_kimi: int | None = None
    report_section_concurrency_minimax: int | None = None
    report_section_provider_1: str | None = None
    report_section_provider_2: str | None = None
    report_section_provider_3: str | None = None
    report_section_provider_4: str | None = None
    report_section_provider_5: str | None = None
    report_section_provider_6: str | None = None
    report_section_provider_7: str | None = None
    report_section_provider_8: str | None = None

    @field_validator("report_section_timeout_seconds", mode="before")
    @classmethod
    def _parse_report_section_timeout(cls, value):
        if isinstance(value, str):
            value = value.split("#", 1)[0].strip()
        if value in (None, ""):
            value = 150.0
        try:
            return max(10.0, float(value))
        except (TypeError, ValueError):
            return 150.0

    @field_validator("report_section_concurrency", mode="before")
    @classmethod
    def _parse_report_section_concurrency(cls, value):
        if isinstance(value, str):
            value = value.split("#", 1)[0].strip()
        if value in (None, ""):
            return 3
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 3

    @field_validator("report_section_concurrency_kimi", "report_section_concurrency_minimax", mode="before")
    @classmethod
    def _parse_report_section_provider_concurrency(cls, value):
        if isinstance(value, str):
            value = value.split("#", 1)[0].strip()
        if value in (None, ""):
            return None
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 3

    @field_validator("deadline_red_days", "deadline_yellow_days", mode="before")
    @classmethod
    def _parse_deadline_days(cls, value, info: ValidationInfo):
        default = 30 if info.field_name == "deadline_red_days" else 90
        if isinstance(value, str):
            value = value.split("#", 1)[0].strip()
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return default

    @field_validator(
        "report_section_provider_1",
        "report_section_provider_2",
        "report_section_provider_3",
        "report_section_provider_4",
        "report_section_provider_5",
        "report_section_provider_6",
        "report_section_provider_7",
        "report_section_provider_8",
        mode="before",
    )
    @classmethod
    def _parse_report_section_provider(cls, value):
        provider = str(value or "").split("#", 1)[0].strip().lower()
        if not provider:
            return None
        if provider not in {"minimax", "kimi", "faker", "openai"}:
            raise ValueError(f"不支持的报告段 provider: {provider}")
        return provider

    def report_section_concurrency_for(self, provider: str) -> int:
        """Resolve provider-specific report concurrency with the global limit as fallback."""
        override = {
            "kimi": self.report_section_concurrency_kimi,
            "minimax": self.report_section_concurrency_minimax,
        }.get((provider or "").strip().lower())
        return override if override is not None else self.report_section_concurrency

    def report_section_provider_for(self, section_id: str) -> str | None:
        sid = str(section_id or "").strip()
        if sid not in {str(index) for index in range(1, 9)}:
            return None
        return getattr(self, f"report_section_provider_{sid}")

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
        """Normalize SQLAlchemy-style DSNs into psycopg-compatible DSNs for LangGraph."""
        if self.postgres_dsn.startswith("postgresql+psycopg://"):
            return self.postgres_dsn.replace("postgresql+psycopg://", "postgresql://", 1)
        return self.postgres_dsn

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
