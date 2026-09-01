from ai_hunter.app.api.routes_files import _retry_blocked_reason


def test_retry_blocked_reason_allows_regular_upload_batches() -> None:
    assert _retry_blocked_reason({"metadata": {}}) == ""


def test_retry_blocked_reason_rejects_manual_review_migration_batches() -> None:
    reason = _retry_blocked_reason(
        {
            "metadata": {
                "retryable": False,
                "retry_policy": "manual_review_required",
                "retry_disabled_reason": "需要人工修复重复行。",
            }
        }
    )

    assert reason == "需要人工修复重复行。"
