from ai_hunter.annual_audit import analysis_service


class _FindingCursor:
    def execute(self, *_args, **_kwargs):
        return None

    def fetchall(self):
        return [
            {
                "id": 11,
                "finding_type": "large_transaction",
                "title": "cash exception",
                "description": "review transaction context",
                "amount": "1000.00",
            }
        ]


def test_attach_finding_identifiers_covers_cycle_views_in_cached_result():
    result = {
        "findings": [
            {
                "finding_type": "large_transaction",
                "title": "cash exception",
                "description": "review transaction context",
                "amount": 1000,
            }
        ],
        "revenue": {"findings": []},
        "receivables": {
            "findings": [
                {
                    "finding_type": "large_transaction",
                    "title": "cash exception",
                    "description": "review transaction context",
                    "amount": "1000.00",
                }
            ]
        },
    }

    analysis_service._attach_finding_identifiers(
        _FindingCursor(),
        result=result,
        analysis_run_id=21,
    )

    assert result["findings"][0]["finding_id"] == 11
    assert result["receivables"]["findings"][0]["finding_id"] == 11
    assert result["findings"][0]["analysis_run_id"] == 21
