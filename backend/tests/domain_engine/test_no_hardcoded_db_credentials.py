"""Static guard against committing database passwords in Python sources."""

from __future__ import annotations

import ast
from pathlib import Path


SOURCE_DIR = Path(__file__).resolve().parents[2] / "ai_hunter" / "domain_engine"


def test_python_sources_do_not_embed_database_passwords():
    marker = "pass" + "word="
    allowed_placeholders = {"xxx", "<redacted>", "${db_password}"}
    offenders: list[str] = []

    for path in sorted(SOURCE_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            value = node.value.lower()
            position = value.find(marker)
            if position < 0:
                continue
            suffix = value[position + len(marker) :].split()[0].strip('"\'')
            if suffix not in allowed_placeholders:
                offenders.append(f"{path.name}:{getattr(node, 'lineno', 0)}")

    assert not offenders, f"hard-coded database password found in: {', '.join(offenders)}"
