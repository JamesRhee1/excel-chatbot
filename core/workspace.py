"""Workspace state container for named tables."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from core.profiler import profile_dataframe
from domains.registry import infer_domain_from_columns

LAST_RESULT_TABLE = "last_result"


@dataclass(frozen=True)
class TableRef:
    """Identifier for a table within a workspace."""

    name: str


@dataclass
class Table:
    """A named DataFrame with profiling metadata."""

    name: str
    df: pd.DataFrame
    profile: dict
    domain: str
    source: str


class Workspace:
    """In-memory collection of named tables."""

    def __init__(self) -> None:
        self._tables: dict[str, Table] = {}

    def add_table(
        self,
        name: str,
        df: pd.DataFrame,
        source: str,
        *,
        domain: str | None = None,
        profile: dict | None = None,
    ) -> str:
        """Register a table; returns the actual name (with _2 suffix on collision)."""
        actual_name = self._resolve_name(name)
        resolved_domain = domain or infer_domain_from_columns([str(c) for c in df.columns.tolist()])
        resolved_profile = profile or profile_dataframe(df, domain=resolved_domain)
        self._tables[actual_name] = Table(
            name=actual_name,
            df=df,
            profile=resolved_profile,
            domain=resolved_domain,
            source=source,
        )
        return actual_name

    def get(self, name: str) -> Table | None:
        return self._tables.get(name)

    def list_tables(self) -> list[str]:
        return list(self._tables.keys())

    def remove(self, name: str) -> bool:
        if name not in self._tables:
            return False
        del self._tables[name]
        return True

    def upsert_table(
        self,
        name: str,
        df: pd.DataFrame,
        source: str,
        *,
        domain: str | None = None,
        profile: dict | None = None,
    ) -> str:
        """Register or replace a table at an exact name (no suffix)."""
        resolved_domain = domain or infer_domain_from_columns([str(c) for c in df.columns.tolist()])
        resolved_profile = profile or profile_dataframe(df, domain=resolved_domain)
        self._tables[name] = Table(
            name=name,
            df=df,
            profile=resolved_profile,
            domain=resolved_domain,
            source=source,
        )
        return name

    def _resolve_name(self, name: str) -> str:
        if name not in self._tables:
            return name
        suffix = 2
        while f"{name}_{suffix}" in self._tables:
            suffix += 1
        return f"{name}_{suffix}"
