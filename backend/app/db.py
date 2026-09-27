import os
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

DEFAULT_URL = "postgresql+psycopg://localhost/winetracker"


@lru_cache
def get_engine() -> Engine:
    return create_engine(os.environ.get("DATABASE_URL", DEFAULT_URL), pool_pre_ping=True)


def query(sql: str, **params) -> list[dict]:
    with get_engine().connect() as conn:
        return [dict(row._mapping) for row in conn.execute(text(sql), params)]
