from pathlib import Path
import re

from dotenv import dotenv_values

from ai_hunter.app.settings import Settings


def test_env_example_keys_are_declared_by_settings():
    example_keys = set(dotenv_values(".env.example"))
    settings_keys = {name.upper() for name in Settings.model_fields}

    assert example_keys - settings_keys == set()


def test_ocr_pdf_settings_load_with_standalone_descriptions(monkeypatch):
    field_names = (
        "OCR_TABLE_ENABLE_PDF",
        "OCR_TABLE_ENABLE_IMAGE",
        "OCR_AUTO_ROTATE_PDF",
        "OCR_AUTO_ROTATE_IMAGE",
        "OCR_PDF_SPLIT_ENABLED",
        "OCR_PDF_SPLIT_THRESHOLD_MB",
        "OCR_PDF_SPLIT_THRESHOLD_PAGES",
        "OCR_PDF_CHUNK_MAX_MB",
        "OCR_PDF_CHUNK_MAX_PAGES",
        "OCR_PDF_CHUNK_CONCURRENCY",
        "OCR_PDF_CHUNK_TIMEOUT_SECONDS",
        "OCR_PDF_CHUNK_MAX_RETRIES",
    )
    for field_name in field_names:
        monkeypatch.delenv(field_name, raising=False)

    settings = Settings(_env_file=".env.example")

    assert settings.ocr_table_enable_pdf is True
    assert settings.ocr_table_enable_image is False
    assert settings.ocr_auto_rotate_pdf is False
    assert settings.ocr_auto_rotate_image is True
    assert settings.ocr_pdf_split_enabled is False
    assert settings.ocr_pdf_split_threshold_mb == 10
    assert settings.ocr_pdf_split_threshold_pages == 10
    assert settings.ocr_pdf_chunk_max_mb == 8
    assert settings.ocr_pdf_chunk_max_pages == 1
    assert settings.ocr_pdf_chunk_concurrency == 1
    assert settings.ocr_pdf_chunk_timeout_seconds == 300
    assert settings.ocr_pdf_chunk_max_retries == 2
    assert Settings(_env_file=None).ocr_pdf_split_enabled is False


def test_agent_recursion_limit_loads_from_env_example(monkeypatch):
    monkeypatch.delenv("AGENT_RECURSION_LIMIT", raising=False)

    assert Settings(_env_file=".env.example").agent_recursion_limit == 8
    assert Settings(_env_file=None).agent_recursion_limit == 8


def test_direct_environment_reads_are_limited_to_dynamic_admin_password_input():
    app_root = Path("ai_hunter/app")
    direct_read_pattern = re.compile(r"\bos\.(?:getenv|environ)")
    matches: dict[str, int] = {}

    for path in app_root.rglob("*.py"):
        count = len(direct_read_pattern.findall(path.read_text(encoding="utf-8")))
        if count:
            matches[path.as_posix()] = count

    assert matches == {"ai_hunter/app/scripts/init_local_admin.py": 2}
