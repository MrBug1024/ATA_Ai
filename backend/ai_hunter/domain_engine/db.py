# ============================================================================
# AI 猎手 FastAPI — 数据库工具
# ============================================================================

import logging
import time

import psycopg2
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from .config import PG_DSN, CPWS_DSN

logger = logging.getLogger("ai_hunter.db")

# 慢查询阈值（毫秒）
SLOW_QUERY_MS = 1000


@contextmanager
def get_conn():
    conn = psycopg2.connect(PG_DSN)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def get_cursor(dict_cursor=True):
    with get_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor if dict_cursor else None)
        try:
            yield cur
        finally:
            cur.close()


def _log_slow(sql, duration_ms):
    """记录慢查询"""
    if duration_ms >= SLOW_QUERY_MS:
        logger.warning("慢查询 (%dms): %s", duration_ms, sql[:300])


def query(sql, params=None):
    t0 = time.time()
    with get_cursor() as cur:
        cur.execute(sql, params)
        result = cur.fetchall()
    _log_slow(sql, int((time.time() - t0) * 1000))
    return result


def query_one(sql, params=None):
    t0 = time.time()
    with get_cursor() as cur:
        cur.execute(sql, params)
        result = cur.fetchone()
    _log_slow(sql, int((time.time() - t0) * 1000))
    return result


def execute(sql, params=None):
    t0 = time.time()
    with get_cursor() as cur:
        cur.execute(sql, params)
        try:
            result = cur.fetchone()
        except psycopg2.ProgrammingError:
            result = None
    _log_slow(sql, int((time.time() - t0) * 1000))
    return result


def execute_returning(sql, params=None):
    t0 = time.time()
    with get_cursor() as cur:
        cur.execute(sql, params)
        result = cur.fetchone()
    _log_slow(sql, int((time.time() - t0) * 1000))
    return result


# ---------------------------------------------------------------------------
# 裁判文书网只读库 (cpwsdata @ 10.0.10.2) — 只查不写
# ---------------------------------------------------------------------------

@contextmanager
def cpws_get_conn():
    """只读连接，不 commit，出错静默 rollback。"""
    conn = psycopg2.connect(CPWS_DSN)
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def cpws_query(sql, params=None):
    """在 cpwsdata 上执行 SELECT，返回 list[RealDictRow]。"""
    t0 = time.time()
    with cpws_get_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params)
        result = cur.fetchall()
        cur.close()
    _log_slow(sql, int((time.time() - t0) * 1000))
    return result


def cpws_query_one(sql, params=None):
    """在 cpwsdata 上执行 SELECT，返回单行或 None。"""
    t0 = time.time()
    with cpws_get_conn() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, params)
        result = cur.fetchone()
        cur.close()
    _log_slow(sql, int((time.time() - t0) * 1000))
    return result
