"""Tests for Workspace table management."""

from __future__ import annotations

import pandas as pd

from core.workspace import TableRef, Workspace
from domains.budget_comparison import normalize_budget_sheet
from tests.test_budget_normalizer import _raw_budget_fixture


def test_add_table_registers_name_and_profile() -> None:
    ws = Workspace()
    df = pd.DataFrame({"이름": ["A"], "매출": [100]})
    name = ws.add_table("sales", df, source="sales.xlsx/Sheet1")
    assert name == "sales"
    table = ws.get("sales")
    assert table is not None
    assert table.domain == "generic"
    assert table.profile["rows"] == 1
    assert table.source == "sales.xlsx/Sheet1"


def test_add_table_collision_gets_numeric_suffix() -> None:
    ws = Workspace()
    df = pd.DataFrame({"a": [1]})
    assert ws.add_table("data", df, source="a.xlsx") == "data"
    assert ws.add_table("data", df, source="b.xlsx") == "data_2"
    assert ws.add_table("data", df, source="c.xlsx") == "data_3"
    assert ws.list_tables() == ["data", "data_2", "data_3"]


def test_add_table_detects_budget_domain() -> None:
    ws = Workspace()
    normalized = normalize_budget_sheet(_raw_budget_fixture())
    name = ws.add_table("budget", normalized, source="budget.xlsx/0")
    table = ws.get(name)
    assert table is not None
    assert table.domain != "generic"
    assert "domain_synonyms" in table.profile
    assert table.profile["domain_synonyms"]


def test_remove_table_and_table_ref() -> None:
    ws = Workspace()
    df = pd.DataFrame({"x": [1]})
    ws.add_table("temp", df, source="t.xlsx")
    ref = TableRef("temp")
    assert ws.get(ref.name) is not None
    assert ws.remove("temp") is True
    assert ws.remove("temp") is False
    assert ws.get(ref.name) is None
    assert ws.list_tables() == []
