"""文字修正 → 权威订正 + 追溯（Tier 2 决策三）：抽取写库 / 加载期合并 / 接口。"""

from fastapi.testclient import TestClient

from ai_hunter.app.main import create_app


# ── extract_correction：抽出后写库（带 operator） + 会话叠加 ──────────────────
def test_extract_correction_persists_with_operator(monkeypatch):
    from ai_hunter.app.graph.nodes import corrections as node
    from ai_hunter.app.graph.schemas import CorrectionModel
    import ai_hunter.app.services.correction_service as cs

    monkeypatch.setattr(node, "_extract_with_llm",
                        lambda q: CorrectionModel(target="水西南路房产", instruction="估值改为800万"))
    captured = {}

    class _Svc:
        def add_correction(self, case_id, **kw):
            captured.update({"case_id": case_id, **kw})
            return {"id": 1}

    monkeypatch.setattr(cs, "get_correction_service", lambda: _Svc())

    out = node.extract_correction({
        "query": "水西南路房产估值不对，按800万", "current_case_id": 116,
        "operator_id": "u-7", "operator_name": "张三",
    })
    # 会话叠加仍在
    assert out["user_corrections"] == ["标的：水西南路房产 -> 强制指令：估值改为800万"]
    assert out["correction_records"][0]["source_query"].startswith("水西南路房产估值")
    # 写库带上了 case_id + 标的/指令 + 操作人
    assert captured["case_id"] == 116
    assert captured["target"] == "水西南路房产" and captured["instruction"] == "估值改为800万"
    assert captured["operator_id"] == "u-7" and captured["operator_name"] == "张三"
    assert captured["origin"] == "chat"


def test_extract_correction_db_failure_keeps_overlay(monkeypatch):
    """库不可达不应拖垮重审：写库抛错被吞，会话叠加照常返回。"""
    from ai_hunter.app.graph.nodes import corrections as node
    from ai_hunter.app.graph.schemas import CorrectionModel
    import ai_hunter.app.services.correction_service as cs

    monkeypatch.setattr(node, "_extract_with_llm",
                        lambda q: CorrectionModel(target="矿权", instruction="解封后重估"))

    class _Boom:
        def add_correction(self, *a, **k):
            raise RuntimeError("db down")

    monkeypatch.setattr(cs, "get_correction_service", lambda: _Boom())
    out = node.extract_correction({"query": "矿权解封后重估", "current_case_id": 116})
    assert out["user_corrections"] == ["标的：矿权 -> 强制指令：解封后重估"]


def test_extract_correction_no_case_skips_db(monkeypatch):
    from ai_hunter.app.graph.nodes import corrections as node
    from ai_hunter.app.graph.schemas import CorrectionModel
    import ai_hunter.app.services.correction_service as cs

    monkeypatch.setattr(node, "_extract_with_llm",
                        lambda q: CorrectionModel(target="x", instruction="y"))
    called = {"n": 0}
    monkeypatch.setattr(cs, "get_correction_service",
                        lambda: called.__setitem__("n", called["n"] + 1))
    node.extract_correction({"query": "改一下", "current_case_id": 0})  # 无案件 → 不写库
    assert called["n"] == 0


# ── fetch_full_context 加载期合并：DB 权威 + overlay 并集去重 ─────────────────
def test_merge_corrections_db_authoritative_union(monkeypatch):
    from ai_hunter.app.graph.nodes import fetch_full_context as fc

    monkeypatch.setattr(fc, "load_corrections_for_state", lambda cid: {
        "user_corrections": ["标的：A -> 强制指令：a改"],
        "correction_records": [{"target": "A", "instruction": "a改", "source_query": "q1"}],
    })
    # overlay 含一条与 DB 重复 + 一条新增（本轮写库失败只在 overlay 的情况）
    state = {
        "current_case_id": 116,
        "user_corrections": ["标的：A -> 强制指令：a改", "标的：B -> 强制指令：b改"],
        "correction_records": [
            {"target": "A", "instruction": "a改", "source_query": "q1"},
            {"target": "B", "instruction": "b改", "source_query": "q2"},
        ],
    }
    out = fc._merge_corrections(state)
    # 去重：A 只一条；并集：B 保留
    assert out["user_corrections"] == ["标的：A -> 强制指令：a改", "标的：B -> 强制指令：b改"]
    assert len(out["correction_records"]) == 2


def test_merge_corrections_db_unreachable_keeps_overlay(monkeypatch):
    from ai_hunter.app.graph.nodes import fetch_full_context as fc

    monkeypatch.setattr(fc, "load_corrections_for_state", lambda cid: {})  # 不可达 → {}
    out = fc._merge_corrections({"current_case_id": 116, "user_corrections": ["x"]})
    assert out == {}  # 不覆盖，调用方保留 overlay


def test_load_corrections_for_state_renders(monkeypatch):
    import ai_hunter.app.services.correction_service as cs

    class _Svc:
        def list_corrections(self, case_id, *, include_history=False):
            return [{"target": "房产", "instruction": "改800万", "source_query": "原话"}]

    monkeypatch.setattr(cs, "get_correction_service", lambda: _Svc())
    out = cs.load_corrections_for_state(116)
    assert out["user_corrections"] == ["标的：房产 -> 强制指令：改800万"]
    assert out["correction_records"][0]["instruction"] == "改800万"


# ── 接口 ────────────────────────────────────────────────────────────────
class _FakeCorrectionService:
    def __init__(self):
        self.added = []

    def list_corrections(self, case_id, *, include_history=False):
        return [{"id": 1, "case_id": case_id, "target": "房产", "instruction": "改800万",
                 "status": "active", "operator_meta": {}}]

    def add_correction(self, case_id, **kw):
        self.added.append((case_id, kw))
        return {"id": 9, "case_id": case_id, "status": "active", "operator_meta": {}, **kw}

    def revoke_correction(self, case_id, correction_id):
        return None if correction_id == 404 else {"id": correction_id, "case_id": case_id,
                                                   "status": "revoked", "operator_meta": {}}


def _client(monkeypatch):
    fake = _FakeCorrectionService()
    monkeypatch.setattr("ai_hunter.app.api.routes_corrections.get_correction_service", lambda: fake)
    return TestClient(create_app()), fake


def test_route_list_corrections(monkeypatch):
    client, _ = _client(monkeypatch)
    r = client.get("/cases/116/corrections")
    assert r.status_code == 200
    assert r.json()["corrections"][0]["target"] == "房产"


def test_route_add_correction_manual(monkeypatch):
    client, fake = _client(monkeypatch)
    r = client.post("/cases/116/corrections",
                    json={"target": "矿权", "instruction": "解封后重估", "operator_name": "李四"})
    assert r.status_code == 200
    assert fake.added[0][1]["origin"] == "manual"
    assert fake.added[0][1]["operator_name"] == "李四"


def test_route_revoke_404(monkeypatch):
    client, _ = _client(monkeypatch)
    r = client.post("/cases/116/corrections/404/revoke")
    assert r.status_code == 404
