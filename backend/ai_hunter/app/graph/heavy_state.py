"""Redis-cached, PostgreSQL-persisted heavy payload store."""

import json
import logging
from functools import lru_cache
from uuid import uuid4

import psycopg

from ..settings import get_settings
from .json_utils import json_dumps_safe, make_json_safe
from ...platform_core import scoped_redis_key


_LOGGER = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_redis_client():
    """Build the configured Redis cache client."""
    settings = get_settings()
    from redis import Redis

    # The configured online Redis is compatible with RESP2 but does not
    # implement the RESP3 HELLO handshake used by newer redis-py defaults.
    return Redis.from_url(settings.redis_dsn, decode_responses=True, protocol=2)


def _serialize_payload(payload: object) -> str:
    """Serialize heavy payloads for Redis/PostgreSQL transport."""
    return json_dumps_safe(payload)


def _deserialize_payload(payload: str) -> object | None:
    """Deserialize heavy payload JSON text back into Python objects."""
    try:
        return json.loads(payload)
    except Exception:
        return None


def _put_postgres_payload(key: str, prefix: str, payload: object) -> None:
    """Persist heavy payload to PostgreSQL for restart-safe recovery."""
    settings = get_settings()
    if not settings.heavy_payload_enable_postgres:
        raise RuntimeError("HEAVY_PAYLOAD_ENABLE_POSTGRES must be true")
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
        raise RuntimeError("PostgreSQL heavy-payload persistence failed") from exc


def _get_postgres_payload(key: str) -> object | None:
    """Recover heavy payload from PostgreSQL when Redis misses."""
    settings = get_settings()
    if not settings.heavy_payload_enable_postgres:
        raise RuntimeError("HEAVY_PAYLOAD_ENABLE_POSTGRES must be true")
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
        raise RuntimeError("PostgreSQL heavy-payload lookup failed") from exc


def _delete_postgres_payload(key: str) -> None:
    """Delete one persisted heavy payload."""
    settings = get_settings()
    if not settings.heavy_payload_enable_postgres:
        raise RuntimeError("HEAVY_PAYLOAD_ENABLE_POSTGRES must be true")
    try:
        with psycopg.connect(settings.postgres_checkpointer_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM public.heavy_payload_store WHERE payload_key = %s", (key,))
            conn.commit()
    except Exception as exc:
        raise RuntimeError("PostgreSQL heavy-payload delete failed") from exc


def put_heavy_payload(prefix: str, payload: object) -> str:
    """Store a large payload out of band and return its lightweight reference key."""
    settings = get_settings()
    key = scoped_redis_key(settings, "heavy", prefix, uuid4().hex)
    normalized_payload = make_json_safe(payload)
    _put_postgres_payload(key, prefix, normalized_payload)
    try:
        _get_redis_client().setex(
            key,
            settings.heavy_payload_ttl_seconds,
            _serialize_payload(normalized_payload),
        )
    except Exception as exc:
        _LOGGER.warning("Redis heavy-payload cache write unavailable: %s", exc)
    return key


def get_heavy_payload(key: str | None) -> object | None:
    """Fetch a heavy payload from Redis, then its PostgreSQL durable copy."""
    if not key:
        return None

    settings = get_settings()
    if f":{settings.business_domain}:heavy:" not in str(key):
        # Do not resolve a reference minted by another domain or by the
        # legacy project, even when Redis/PostgreSQL is physically shared.
        return None

    redis_client = _get_redis_client()
    try:
        payload_json = redis_client.get(key)
        if payload_json:
            payload = _deserialize_payload(payload_json)
            if payload is not None:
                return payload
    except Exception as exc:
        _LOGGER.warning("Redis heavy-payload cache read unavailable: %s", exc)

    payload = _get_postgres_payload(key)
    if payload is not None:
        try:
            redis_client.setex(
                key,
                get_settings().heavy_payload_ttl_seconds,
                _serialize_payload(payload),
            )
        except Exception as exc:
            _LOGGER.warning("Redis heavy-payload cache backfill unavailable: %s", exc)
    return payload


def clear_heavy_payload(key: str | None) -> None:
    """Delete one heavy payload from Redis and PostgreSQL."""
    if not key:
        return
    settings = get_settings()
    if f":{settings.business_domain}:heavy:" not in str(key):
        return
    try:
        _get_redis_client().delete(key)
    except Exception as exc:
        _LOGGER.warning("Redis heavy-payload cache delete unavailable: %s", exc)
    _delete_postgres_payload(key)
