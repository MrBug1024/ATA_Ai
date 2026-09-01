from __future__ import annotations

from contextlib import contextmanager

from ai_hunter.annual_audit import task_repository


class _Cursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []
        self._last_kind = ""
        self._insert_id = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=()):
        normalized = " ".join(str(statement).split())
        self.executed.append((normalized, tuple(params)))
        self._last_kind = normalized.split(" ", 1)[0]
        if normalized.startswith("INSERT INTO annual_task") and params[2] == "bad task":
            raise RuntimeError("synthetic insert failure")
        if normalized.startswith("INSERT INTO annual_task"):
            self._insert_id += 1

    def fetchone(self):
        if self._last_kind == "SELECT":
            return None
        if self._last_kind == "INSERT":
            return {"id": self._insert_id}
        return None


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor
        self.commits = 0

    def cursor(self):
        return self._cursor

    def commit(self) -> None:
        self.commits += 1


def test_batch_task_failure_rolls_back_only_its_savepoint(monkeypatch) -> None:
    cursor = _Cursor()
    connection = _Connection(cursor)

    @contextmanager
    def connect(_settings):
        yield connection

    monkeypatch.setattr(task_repository, "get_engagement", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(task_repository, "postgres_connection", connect)

    result = task_repository.create_task_batch(
        7,
        [{"action": "good task"}, {"action": "bad task"}],
        settings=object(),
    )

    statements = [statement for statement, _params in cursor.executed]
    assert result["tasks_created"] == 1
    assert result["tasks_failed"] == 1
    assert "ROLLBACK TO SAVEPOINT annual_task_1" in statements
    assert "RELEASE SAVEPOINT annual_task_0" in statements
    assert "RELEASE SAVEPOINT annual_task_1" in statements
    assert connection.commits == 1
