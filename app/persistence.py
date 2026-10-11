"""Durable snapshots for the bounded, single-worker demo stores.

DATABASE_URL is optional locally. When configured, database failures propagate;
the service never silently falls back to volatile storage.
"""
import os
from copy import deepcopy
from contextlib import contextmanager
from functools import wraps

import psycopg
from psycopg.types.json import Jsonb


@contextmanager
def connection(url=None):
    with psycopg.connect(url or os.environ["DATABASE_URL"], connect_timeout=10) as conn:
        yield conn


def enabled():
    return bool(os.getenv("DATABASE_URL"))


def initialize():
    if enabled():
        with connection(os.getenv("DATABASE_URL_UNPOOLED")) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS modellab_state (
                    namespace text PRIMARY KEY,
                    payload jsonb NOT NULL,
                    updated_at timestamptz NOT NULL DEFAULT now()
                )
            """)


def load(namespace):
    if not enabled():
        return None
    with connection() as conn:
        row = conn.execute(
            "SELECT payload FROM modellab_state WHERE namespace = %s", (namespace,)
        ).fetchone()
    return row[0] if row else None


def save(namespace, payload):
    if enabled():
        with connection() as conn:
            conn.execute("""
                INSERT INTO modellab_state (namespace, payload) VALUES (%s, %s)
                ON CONFLICT (namespace) DO UPDATE
                SET payload = EXCLUDED.payload, updated_at = now()
            """, (namespace, Jsonb(payload)))


def healthy():
    if enabled():
        with connection() as conn:
            conn.execute("SELECT 1").fetchone()
    return True


def durable(lock, namespace, stores, payload=None, skip=None):
    """Serialize mutations and roll RAM back if the database write fails."""
    def decorate(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            with lock:
                persist = enabled() and not (skip and skip(*args, **kwargs))
                before = deepcopy(stores) if persist else None
                try:
                    result = fn(*args, **kwargs)
                    if persist:
                        save(namespace, payload() if payload else stores)
                    return result
                except Exception:
                    if before is not None:
                        for key, store in stores.items():
                            if isinstance(store, dict):
                                store.clear()
                                store.update(before[key])
                            else:
                                store[:] = before[key]
                    raise
        return wrapped
    return decorate
