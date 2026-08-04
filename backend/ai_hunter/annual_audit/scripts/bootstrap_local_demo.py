"""Create the empty local demo engagement without inventing financial facts."""

from __future__ import annotations

from ai_hunter.annual_audit.engagement_repository import create_engagement
from ai_hunter.annual_audit.report_service import generate_annual_report_draft


def main() -> None:
    engagement = create_engagement(
        {
            "case_name": "北京有限公司 2023 年度年审演示",
            "entity_name": "北京有限公司",
            "fiscal_year": 2023,
            "company_id": "co_annual_local",
            "owner_id": "local_super_admin",
            "created_by": "local_super_admin",
        }
    )
    report = generate_annual_report_draft(
        int(engagement["case_id"]),
        created_by="local_super_admin",
    )
    artifacts = report.get("artifacts") or {}
    print(
        "annual demo ready: "
        f"case_id={engagement['case_id']} "
        f"deduplicated={bool(engagement.get('deduplicated'))} "
        f"report_version={(artifacts.get('report') or {}).get('version')} "
        f"workpapers={len(artifacts.get('workpapers') or [])}"
    )


if __name__ == "__main__":
    main()
