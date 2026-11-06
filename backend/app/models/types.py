"""Portable column types.

The same models run on MySQL/MariaDB (the ELM target, inside `proflow_uat`), SQLite (tests) and PostgreSQL.

* ``UTCDateTime`` always stores UTC and always returns an aware UTC datetime. On MySQL it is ``DATETIME(6)``, because the
  default ``DATETIME`` drops microseconds and the hash-chained audit trail hashes the full timestamp.
* ``LongText`` is ``LONGTEXT`` on MySQL, because MySQL ``TEXT`` stops at 64 KB and baselines, workflow specs and import
  reports can be larger.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Text
from sqlalchemy.dialects import mysql
from sqlalchemy.types import TypeDecorator

LongText = Text().with_variant(mysql.LONGTEXT(), "mysql", "mariadb")


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name in ("mysql", "mariadb"):
            return dialect.type_descriptor(mysql.DATETIME(fsp=6))
        return dialect.type_descriptor(DateTime(timezone=True))

    def process_bind_param(self, value: datetime | None, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        value = value.astimezone(UTC)
        return value.replace(tzinfo=None) if dialect.name in ("mysql", "mariadb", "sqlite") else value

    def process_result_value(self, value: datetime | None, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
