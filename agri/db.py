"""Thin PostgreSQL access layer (psycopg 3 + pgvector)."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import get_settings

_pool: ConnectionPool | None = None


def _configure(conn: psycopg.Connection) -> None:
    from pgvector.psycopg import register_vector

    try:
        register_vector(conn)
    except psycopg.ProgrammingError:
        pass  # extension not created yet (first init)


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            get_settings().database_url, min_size=1, max_size=10, configure=_configure,
            kwargs={"row_factory": dict_row, "autocommit": True}, open=True,
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def conn() -> Iterator[psycopg.Connection]:
    with pool().connection() as c:
        yield c


def fetchall(sql: str, params: Any = None) -> list[dict]:
    with conn() as c:
        return c.execute(sql, params).fetchall()


def fetchone(sql: str, params: Any = None) -> dict | None:
    with conn() as c:
        return c.execute(sql, params).fetchone()


def execute(sql: str, params: Any = None) -> None:
    with conn() as c:
        c.execute(sql, params)


def init_db() -> None:
    sql = (Path(__file__).parent / "schema.sql").read_text()
    with psycopg.connect(get_settings().database_url, autocommit=True) as c:
        c.execute(sql)
    close_pool()  # reconnect so the vector type gets registered
