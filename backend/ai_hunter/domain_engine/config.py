# ============================================================================
# AI 猎手 FastAPI — 配置文件
# ============================================================================

import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv

# 统一服务以 backend/.env 为主；迁移时仅用 .env.domain.local 补齐旧服务
# 尚未写入统一配置的本地密钥。两者均被版本控制忽略。
BACKEND_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_ROOT / ".env")
load_dotenv(BACKEND_ROOT / ".env.domain.local", override=False)

# ---------------------------------------------------------------------------
# 数据库
# ---------------------------------------------------------------------------
PG_DSN = os.getenv("PG_DSN", "") or os.getenv("POSTGRES_DSN", "").replace("+psycopg", "")
AUDIT_API_TOKEN = os.getenv("AUDIT_API_TOKEN", "")

# 裁判文书网只读库（只查不写）
# 表结构（Phase-0 已探查）：
#   case_metadata  — 元数据主表（id PK, case_no, title, court, doc_type, judge_date ...）
#   case_entities  — 当事人（case_id FK→case_metadata.id, role, name）
#   case_sections  — 正文分段（case_id, section_type, content）
#   case_search_chunks — 向量块（case_id, section_id FK→case_sections.id, embedding vector(1532)）
CPWS_DSN = os.getenv("CPWS_DSN", "")
if not CPWS_DSN and os.getenv("CPWS_DB_HOST"):
    cpws_user = quote_plus(os.getenv("CPWS_DB_USER", "postgres"))
    cpws_password = quote_plus(os.getenv("CPWS_DB_PASSWORD", ""))
    cpws_auth = f"{cpws_user}:{cpws_password}" if cpws_password else cpws_user
    CPWS_DSN = (
        f"postgresql://{cpws_auth}@{os.getenv('CPWS_DB_HOST')}:{os.getenv('CPWS_DB_PORT', '5432')}"
        f"/{os.getenv('CPWS_DB_NAME', 'cpwsdata')}"
    )
CPWS_EMBED_DIM = int(os.getenv("CPWS_EMBED_DIM", "1532"))  # case_search_chunks.embedding 维度

# ---------------------------------------------------------------------------
# LLM 模型配置（二选一，通过环境变量 LLM_PROVIDER 切换）
# ---------------------------------------------------------------------------
LLM_PROVIDER = os.getenv("NPA_ENGINE_LLM_PROVIDER", os.getenv("LLM_DEFAULT_PROVIDER", "minimax"))

# Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# MiniMax
MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_BASE_URL = "https://api.minimaxi.com/v1"
MINIMAX_MODEL = os.getenv("NPA_ENGINE_MINIMAX_MODEL", os.getenv("MINIMAX_MODEL_AGENT", "MiniMax-M2.5"))

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_DIR = os.getenv("LOG_DIR", "logs")

# ---------------------------------------------------------------------------
# 企查查 API
# ---------------------------------------------------------------------------
QICHACHA_API_KEY = os.getenv("QICHACHA_API_KEY", "")
QICHACHA_SECRET_KEY = os.getenv("QICHACHA_SECRET_KEY", "")
QICHACHA_BASE_URL = os.getenv("QICHACHA_BASE_URL", "https://api.qichacha.com")


def get_llm_config():
    """返回当前激活的 LLM 配置"""
    if LLM_PROVIDER == "minimax":
        return {
            "api_key": MINIMAX_API_KEY,
            "base_url": MINIMAX_BASE_URL,
            "model": MINIMAX_MODEL,
        }
    else:
        return {
            "api_key": GEMINI_API_KEY,
            "base_url": GEMINI_BASE_URL,
            "model": GEMINI_MODEL,
        }
