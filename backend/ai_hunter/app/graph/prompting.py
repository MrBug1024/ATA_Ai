"""Helpers for loading prompt templates from the local prompts directory."""

from functools import lru_cache
from pathlib import Path


PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Load a prompt file once and keep it hot in memory for repeated graph runs."""
    return (PROMPTS_DIR / name).read_text(encoding="utf-8").strip()
