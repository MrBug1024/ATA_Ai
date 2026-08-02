# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

This repo maintains its primary agent guidance in **[AGENTS.md](AGENTS.md)** — commands, directory map, test conventions, config/provider gotchas, and "look before you change" rules all live there. Read it first.

@AGENTS.md

## Quick reference

- **Install / run / test**: `python3 -m pip install -e '.[dev]'` · `uvicorn ai_hunter.app.main:app --host 0.0.0.0 --port 8081 --reload` · `pytest -q` (baseline `14 passed`).
- **Single test**: `pytest tests/test_main_graph.py -q` or `pytest tests/test_main_graph.py::<test_name> -q`. Only `tests/` is collected (`testpaths` is pinned); root-level `test_*.py` and `scripts/test_*.py` hit live services — never run them under pytest.
- **No lint / format / typecheck / CI exists** — don't invent those commands.
- **Top-level graph wiring is the single source of truth** in [ai_hunter/app/graph/main.py](ai_hunter/app/graph/main.py): `normalize_input → hydrate_memory_context → resolve_case_context → hydrate_case_graph_context → (ingest_graph?) → classify_intent → {full_audit_graph | drilldown_agent_graph | extract_correction→full_audit_graph} → (create_tasks?) → finalize_answer → persist_conversation_memory`. State fields are declared in [ai_hunter/app/graph/state.py](ai_hunter/app/graph/state.py).
- **Three subgraphs** ([ai_hunter/app/subgraphs/](ai_hunter/app/subgraphs/)): `ingest_graph`, `full_audit_graph`, `drilldown_agent_graph`. Drilldown tools must be registered in [ai_hunter/app/tools/registry.py](ai_hunter/app/tools/registry.py) to be discoverable.
- **Manual end-to-end smoke**: `case_id=116` is the standard demo case (exercises the `full_audit` path).
