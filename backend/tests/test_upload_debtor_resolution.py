import pytest
from fastapi import HTTPException

from ai_hunter.app.api import _upload_helpers as helpers


class _FakeCaseAPI:
    def __init__(self, profile=None, error: Exception | None = None):
        self.profile = profile
        self.error = error

    def get_case_profile_sync(self, case_id, *, identity=None):
        if self.error:
            raise self.error
        return self.profile


def _use_profile(monkeypatch, profile):
    monkeypatch.setattr(helpers, "get_case_api_client", lambda: _FakeCaseAPI(profile))


def test_resolve_effective_debtor_matches_debtor_id_and_entity_name(monkeypatch):
    _use_profile(
        monkeypatch,
        {
            "debtors": [
                {"debtor_id": 76, "entity_name": "钟山区老鹰山镇晨光煤矿"},
            ],
            "parties": [
                {
                    "party_id": 2,
                    "party_name": "中国中信金融资产管理股份有限公司",
                    "party_role": "asset_purchaser",
                }
            ],
        },
    )

    result = helpers.resolve_effective_debtor(case_id=116, debtor_id=76)

    assert result.debtor_id == 76
    assert result.debtor_name == "钟山区老鹰山镇晨光煤矿"
    assert result.source == "debtor_id"


def test_resolve_effective_debtor_supports_legacy_name_field(monkeypatch):
    _use_profile(monkeypatch, {"debtors": [{"debtor_id": 7, "name": "旧接口债务人"}]})

    result = helpers.resolve_effective_debtor(case_id=1)

    assert result.debtor_id == 7
    assert result.debtor_name == "旧接口债务人"
    assert result.source == "single_case_debtor"


def test_resolve_effective_debtor_rejects_asset_purchaser_as_debtor(monkeypatch):
    _use_profile(
        monkeypatch,
        {
            "debtors": [{"debtor_id": 76, "entity_name": "钟山区老鹰山镇晨光煤矿"}],
            "parties": [
                {
                    "party_id": 2,
                    "party_name": "中国中信金融资产管理股份有限公司",
                    "party_role": "asset_purchaser",
                }
            ],
        },
    )

    with pytest.raises(HTTPException) as exc:
        helpers.resolve_effective_debtor(
            case_id=116,
            debtor_name="中国中信金融资产管理股份有限公司",
        )

    assert exc.value.status_code == 409
    assert "主数据不一致" in str(exc.value.detail)


def test_resolve_effective_debtor_requires_id_for_multiple_debtors(monkeypatch):
    _use_profile(
        monkeypatch,
        {
            "debtors": [
                {"debtor_id": 1, "entity_name": "债务人甲"},
                {"debtor_id": 2, "entity_name": "债务人乙"},
            ]
        },
    )

    with pytest.raises(HTTPException) as exc:
        helpers.resolve_effective_debtor(case_id=10)

    assert exc.value.status_code == 409
    assert "多个债务人" in str(exc.value.detail)


def test_resolve_effective_debtor_fails_when_profile_unavailable(monkeypatch):
    monkeypatch.setattr(
        helpers,
        "get_case_api_client",
        lambda: _FakeCaseAPI(error=RuntimeError("upstream unavailable")),
    )

    with pytest.raises(HTTPException) as exc:
        helpers.resolve_effective_debtor(case_id=116, debtor_id=76)

    assert exc.value.status_code == 502
