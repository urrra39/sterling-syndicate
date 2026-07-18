from __future__ import annotations

"""Dialect-agnostic column types — PostgreSQL when available, SQLite-safe otherwise."""

import json
import uuid
from typing import Any, List, Optional

from sqlalchemy import String, Text, TypeDecorator
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PG_UUID
from sqlalchemy.types import CHAR


class GUID(TypeDecorator):
    """UUID as native Postgres UUID, or CHAR(36) on SQLite."""

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):  # type: ignore[no-untyped-def]
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value: Any, dialect) -> Any:  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        return str(value) if not isinstance(value, uuid.UUID) else str(value)

    def process_result_value(self, value: Any, dialect) -> Optional[uuid.UUID]:  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


class JSONList(TypeDecorator):
    """List[str|float] as Postgres ARRAY, or JSON text on SQLite."""

    impl = Text
    cache_ok = True

    def __init__(self, item_type: Any = String(255), *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._item_type = item_type

    def load_dialect_impl(self, dialect):  # type: ignore[no-untyped-def]
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(self._item_type))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: Any, dialect) -> Any:  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if dialect.name == "postgresql":
            return list(value)
        return json.dumps(list(value))

    def process_result_value(self, value: Any, dialect) -> Optional[List[Any]]:  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if dialect.name == "postgresql":
            return list(value)
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            if value in ("{}",):
                return []
            try:
                parsed = json.loads(value)
                return list(parsed) if isinstance(parsed, list) else []
            except json.JSONDecodeError:
                return []
        return list(value)
