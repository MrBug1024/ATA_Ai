"""Strict, loader-free Jinja syntax analysis for untrusted templates."""

from __future__ import annotations

import re
from typing import Any

from jinja2 import Environment, TemplateSyntaxError, meta, nodes


ALLOWED_FILTERS = frozenset(
    {"default", "join", "length", "lower", "replace", "trim", "upper"}
)
_DOCXTPL_BLOCK_PREFIX = re.compile(r"{%\s*[ptrc]\s+", re.IGNORECASE)
_DOCXTPL_VARIABLE_PREFIX = re.compile(r"{{\s*[rp]\s+", re.IGNORECASE)
_FORBIDDEN_NODE_TYPES = (
    nodes.Assign,
    nodes.AssignBlock,
    nodes.Call,
    nodes.CallBlock,
    nodes.Extends,
    nodes.FilterBlock,
    nodes.FromImport,
    nodes.Import,
    nodes.Include,
    nodes.Macro,
)


def _safe_key(value: Any) -> str:
    key = str(value or "")
    if (
        not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,127}", key)
        or key.startswith("_")
        or "__" in key
    ):
        return ""
    return key


def _analyze_scoped_access(parsed: nodes.Template) -> tuple[list[str], list[dict[str, Any]]]:
    forbidden: set[str] = set()
    loops: list[dict[str, Any]] = []

    def visit(node: nodes.Node, locals_in_scope: dict[str, dict[str, Any]]) -> None:
        if isinstance(node, nodes.For):
            if not isinstance(node.target, nodes.Name) or not isinstance(node.iter, nodes.Name):
                forbidden.add("UnsafeLoopExpression")
                for child in node.iter_child_nodes():
                    visit(child, locals_in_scope)
                return
            alias = node.target.name
            source = node.iter.name
            if not _safe_key(alias) or not _safe_key(source):
                forbidden.add("PrivateIdentifier")
                return
            metadata: dict[str, Any] = {
                "variable": alias,
                "source": source,
                "accessed_keys": set(),
            }
            loops.append(metadata)
            nested_scope = {**locals_in_scope, alias: metadata}
            visit(node.iter, locals_in_scope)
            for child in node.body:
                visit(child, nested_scope)
            for child in node.else_:
                visit(child, locals_in_scope)
            if node.test is not None:
                visit(node.test, nested_scope)
            return
        if isinstance(node, nodes.Getattr):
            if isinstance(node.node, nodes.Name) and node.node.name in locals_in_scope:
                key = _safe_key(node.attr)
                if key:
                    locals_in_scope[node.node.name]["accessed_keys"].add(key)
                    return
            forbidden.add("Getattr")
            return
        if isinstance(node, nodes.Getitem):
            if (
                isinstance(node.node, nodes.Name)
                and node.node.name in locals_in_scope
                and isinstance(node.arg, nodes.Const)
                and isinstance(node.arg.value, str)
            ):
                key = _safe_key(node.arg.value)
                if key:
                    locals_in_scope[node.node.name]["accessed_keys"].add(key)
                    return
            forbidden.add("Getitem")
            return
        for child in node.iter_child_nodes():
            visit(child, locals_in_scope)

    visit(parsed, {})
    normalized_loops = [
        {
            "variable": item["variable"],
            "source": item["source"],
            "accessed_keys": sorted(item["accessed_keys"]),
        }
        for item in loops
    ]
    return sorted(forbidden), normalized_loops


def analyze_jinja_template(
    template_text: str,
    *,
    docxtpl_extensions: bool = False,
    allowed_filters: frozenset[str] = ALLOWED_FILTERS,
) -> dict[str, Any]:
    normalized = str(template_text or "")
    if docxtpl_extensions:
        normalized = _DOCXTPL_BLOCK_PREFIX.sub("{% ", normalized)
        normalized = _DOCXTPL_VARIABLE_PREFIX.sub("{{ ", normalized)
    environment = Environment(loader=None, autoescape=False)
    environment.globals.clear()
    try:
        parsed = environment.parse(normalized)
    except TemplateSyntaxError as exc:
        return {
            "ok": False,
            "error": "JINJA_SYNTAX_ERROR",
            "message": f"Jinja syntax is invalid at line {exc.lineno}",
            "undeclared_variables": [],
            "filters": [],
            "forbidden_constructs": [],
            "loop_accesses": [],
        }

    forbidden = {
        type(node).__name__ for node in parsed.find_all(_FORBIDDEN_NODE_TYPES)
    }
    scoped_forbidden, loop_accesses = _analyze_scoped_access(parsed)
    forbidden.update(scoped_forbidden)
    filters = sorted({node.name for node in parsed.find_all(nodes.Filter)})
    rejected_filters = sorted(set(filters) - set(allowed_filters))
    undeclared = sorted(meta.find_undeclared_variables(parsed))
    if any("__" in value or value.startswith("_") for value in undeclared):
        forbidden.add("PrivateIdentifier")
    loop_count = sum(1 for _ in parsed.find_all(nodes.For))
    if loop_count > 50:
        forbidden.add("LoopLimit")
    ok = not forbidden and not rejected_filters
    return {
        "ok": ok,
        "error": "" if ok else "UNSAFE_JINJA_TEMPLATE",
        "message": "" if ok else "Jinja template contains forbidden expressions",
        "undeclared_variables": undeclared,
        "filters": filters,
        "rejected_filters": rejected_filters,
        "forbidden_constructs": sorted(forbidden),
        "loop_count": loop_count,
        "loop_accesses": loop_accesses,
    }


__all__ = ["ALLOWED_FILTERS", "analyze_jinja_template"]
