from ai_hunter.app.graph.route_shadow import build_route_shadow


def test_route_shadow_compares_legacy_and_business_line_targets(monkeypatch):
    monkeypatch.setattr(
        "ai_hunter.app.graph.route_shadow.get_settings",
        lambda: type("Settings", (), {"router_execution_mode": "legacy"})(),
    )

    shadow = build_route_shadow(
        {
            "business_line": "operator",
            "capability": "case.profile",
            "needs_clarification": False,
        }
    )

    assert shadow == {
        "phase": "2.5.4",
        "configured_mode": "legacy",
        "active_mode": "legacy",
        "business_line": "operator",
        "capability": "case.profile",
        "access_mode": "read",
        "legacy_target": "drilldown_agent_graph",
        "business_line_target": "operator_subgraph",
        "business_line_leaf": "query_case_profile",
        "target_differs": True,
        "business_line_execution_enabled": True,
        "write_shadow_blocked": False,
        "shadow_business_logic_executed": False,
    }


def test_route_shadow_activates_migrated_write_in_business_line_mode(monkeypatch):
    monkeypatch.setattr(
        "ai_hunter.app.graph.route_shadow.get_settings",
        lambda: type("Settings", (), {"router_execution_mode": "business_line"})(),
    )

    shadow = build_route_shadow(
        {
            "business_line": "supervision",
            "capability": "task.write",
            "needs_clarification": False,
        }
    )

    assert shadow["configured_mode"] == "business_line"
    assert shadow["active_mode"] == "business_line"
    assert shadow["business_line_execution_enabled"] is True
    assert shadow["business_line_leaf"] == "write_task_command"
    assert shadow["write_shadow_blocked"] is False
    assert shadow["shadow_business_logic_executed"] is False


def test_route_shadow_keeps_clarification_outside_business_line_subgraphs(monkeypatch):
    monkeypatch.setattr(
        "ai_hunter.app.graph.route_shadow.get_settings",
        lambda: type("Settings", (), {"router_execution_mode": "legacy"})(),
    )

    shadow = build_route_shadow(
        {
            "business_line": "operator",
            "capability": "material.upload",
            "needs_clarification": True,
        }
    )

    assert shadow["legacy_target"] == "clarify_route"
    assert shadow["business_line_target"] == "clarify_route"
    assert shadow["target_differs"] is False
    assert shadow["business_line_execution_enabled"] is True
    assert shadow["write_shadow_blocked"] is False


def test_route_shadow_activates_only_migrated_read_capability(monkeypatch):
    monkeypatch.setattr(
        "ai_hunter.app.graph.route_shadow.get_settings",
        lambda: type("Settings", (), {"router_execution_mode": "business_line"})(),
    )

    shadow = build_route_shadow(
        {"business_line": "operator", "capability": "case.profile", "needs_clarification": False}
    )

    assert shadow["active_mode"] == "business_line"
    assert shadow["business_line_target"] == "operator_subgraph"
    assert shadow["business_line_leaf"] == "query_case_profile"
    assert shadow["write_shadow_blocked"] is False


def test_route_shadow_activates_migrated_specialized_graph(monkeypatch):
    monkeypatch.setattr(
        "ai_hunter.app.graph.route_shadow.get_settings",
        lambda: type("Settings", (), {"router_execution_mode": "business_line"})(),
    )

    shadow = build_route_shadow(
        {"business_line": "audit_analysis", "capability": "audit.full", "needs_clarification": False}
    )

    assert shadow["active_mode"] == "business_line"
    assert shadow["business_line_target"] == "audit_analysis_subgraph"
    assert shadow["business_line_leaf"] == "full_audit_graph"
    assert shadow["write_shadow_blocked"] is False


def test_route_shadow_records_unknown_capability_without_execution(monkeypatch):
    monkeypatch.setattr(
        "ai_hunter.app.graph.route_shadow.get_settings",
        lambda: type("Settings", (), {"router_execution_mode": "legacy"})(),
    )

    shadow = build_route_shadow({"business_line": "common", "capability": "unknown"})

    assert shadow["active_mode"] == "legacy"
    assert shadow["shadow_business_logic_executed"] is False
    assert shadow["error"] == "unregistered route decision"
