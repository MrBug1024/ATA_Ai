"""Hybrid heavy-payload store backed by Redis cache plus PostgreSQL persistence."""

import atexit
import json
import logging
from collections import OrderedDict
from functools import lru_cache
from uuid import uuid4

import psycopg

from ..settings import get_settings
from .json_utils import json_dumps_safe, make_json_safe


MAX_HEAVY_STATE_ITEMS = 256
_HEAVY_STATE: "OrderedDict[str, object]" = OrderedDict()
_LOGGER = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_redis_client():
    """Build a Redis client lazily so local tests can still run without Redis."""
    settings = get_settings()
    if not settings.redis_url:
        return None
    try:
        from redis import Redis

        return Redis.from_url(settings.redis_url, decode_responses=True)
    except Exception as exc:
        _LOGGER.warning("Redis heavy-payload cache unavailable: %s", exc)
        return None


def _serialize_payload(payload: object) -> str:
    """Serialize heavy payloads for Redis/PostgreSQL transport."""
    return json_dumps_safe(payload)


def _deserialize_payload(payload: str) -> object | None:
    """Deserialize heavy payload JSON text back into Python objects."""
    try:
        return json.loads(payload)
    except Exception:
        return None


def _evict_if_needed() -> None:
    """Prevent the in-process fallback cache from growing without bound."""
    while len(_HEAVY_STATE) > MAX_HEAVY_STATE_ITEMS:
        _HEAVY_STATE.popitem(last=False)


def _put_postgres_payload(key: str, prefix: str, payload: object) -> None:
    """Persist heavy payload to PostgreSQL for restart-safe recovery."""
    settings = get_settings()
    if not settings.heavy_payload_enable_postgres:
        return
    try:
        with psycopg.connect(settings.postgres_checkpointer_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO public.heavy_payload_store
                        (payload_key, payload_type, payload_json)
                    VALUES (%s, %s, %s::jsonb)
                    ON CONFLICT (payload_key)
                    DO UPDATE SET
                        payload_type = EXCLUDED.payload_type,
                        payload_json = EXCLUDED.payload_json,
                        updated_at = NOW()
                    """,
                    (key, prefix, _serialize_payload(payload)),
                )
            conn.commit()
    except Exception as exc:
        _LOGGER.warning("PostgreSQL heavy-payload persistence unavailable: %s", exc)


def _get_postgres_payload(key: str) -> object | None:
    """Recover heavy payload from PostgreSQL when Redis misses."""
    settings = get_settings()
    if not settings.heavy_payload_enable_postgres:
        return None
    try:
        with psycopg.connect(settings.postgres_checkpointer_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT payload_json::text
                    FROM public.heavy_payload_store
                    WHERE payload_key = %s
                    """,
                    (key,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return _deserialize_payload(row[0])
    except Exception as exc:
        _LOGGER.warning("PostgreSQL heavy-payload lookup unavailable: %s", exc)
        return None


def _delete_postgres_payload(key: str) -> None:
    """Delete one persisted heavy payload."""
    settings = get_settings()
    if not settings.heavy_payload_enable_postgres:
        return
    try:
        with psycopg.connect(settings.postgres_checkpointer_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM public.heavy_payload_store WHERE payload_key = %s", (key,))
            conn.commit()
    except Exception as exc:
        _LOGGER.warning("PostgreSQL heavy-payload delete unavailable: %s", exc)


def put_heavy_payload(prefix: str, payload: object) -> str:
    """Store a large payload out of band and return its lightweight reference key."""
    settings = get_settings()
    key = f"{prefix}:{uuid4().hex}"
    normalized_payload = make_json_safe(payload)
    _HEAVY_STATE[key] = normalized_payload
    _evict_if_needed()

    redis_client = _get_redis_client()
    if redis_client is not None:
        try:
            redis_client.setex(key, settings.heavy_payload_ttl_seconds, _serialize_payload(normalized_payload))
        except Exception as exc:
            _LOGGER.warning("Redis heavy-payload write unavailable: %s", exc)

    _put_postgres_payload(key, prefix, normalized_payload)
    return key


def get_heavy_payload(key: str | None) -> object | None:
    """Fetch a heavy payload with local-memory, Redis, then PostgreSQL fallback."""
    if not key:
        return None

    payload = _HEAVY_STATE.get(key)
    if payload is not None:
        _HEAVY_STATE.move_to_end(key)
        return payload

    redis_client = _get_redis_client()
    if redis_client is not None:
        try:
            payload_json = redis_client.get(key)
            if payload_json:
                payload = _deserialize_payload(payload_json)
                if payload is not None:
                    _HEAVY_STATE[key] = payload
                    _evict_if_needed()
                    return payload
        except Exception as exc:
            _LOGGER.warning("Redis heavy-payload read unavailable: %s", exc)

    payload = _get_postgres_payload(key)
    if payload is not None:
        _HEAVY_STATE[key] = payload
        _evict_if_needed()
        if redis_client is not None:
            try:
                redis_client.setex(
                    key,
                    get_settings().heavy_payload_ttl_seconds,
                    _serialize_payload(payload),
                )
            except Exception as exc:
                _LOGGER.warning("Redis heavy-payload backfill unavailable: %s", exc)
    return payload


def clear_heavy_payload(key: str | None) -> None:
    """Delete one heavy payload from memory, Redis, and PostgreSQL."""
    if not key:
        return
    _HEAVY_STATE.pop(key, None)
    redis_client = _get_redis_client()
    if redis_client is not None:
        try:
            redis_client.delete(key)
        except Exception as exc:
            _LOGGER.warning("Redis heavy-payload delete unavailable: %s", exc)
    _delete_postgres_payload(key)


def clear_all_heavy_payloads() -> None:
    """Reset the in-memory fallback cache on shutdown."""
    _HEAVY_STATE.clear()


atexit.register(clear_all_heavy_payloads)
