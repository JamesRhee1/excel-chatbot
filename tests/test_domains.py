"""Tests for domain pack detection and registry."""

from __future__ import annotations

import pandas as pd
import pytest

from domains.budget_comparison import detect_budget_sheet, normalize_budget_sheet
from domains.generic import GENERIC_PACK
from domains.registry import enrich_profile, get_pack, infer_domain_from_columns, match_pack
from tests.test_budget_normalizer import _raw_budget_fixture


def test_detect_budget_sheet_success() -> None:
    raw = _raw_budget_fixture()
    pack = match_pack(raw)
    assert pack.name == "budget_comparison"
    assert detect_budget_sheet(raw) is True


def test_detect_budget_sheet_failure_uses_generic() -> None:
    raw = pd.DataFrame(
        [
            ["이름", "매출", "비고"],
            ["A", 100, "x"],
            ["B", 200, "y"],
        ]
    )
    pack = match_pack(raw)
    assert pack.name == "generic"
    assert detect_budget_sheet(raw) is False


def test_generic_pack_normalize_simple_table() -> None:
    raw = pd.DataFrame(
        [
            ["이름", "매출"],
            ["A", 100],
            ["B", 200],
        ]
    )
    df = GENERIC_PACK.normalize_raw(raw)
    assert list(df.columns) == ["이름", "매출"]
    assert len(df) == 2


def test_enrich_profile_budget_domain_metadata() -> None:
    raw = _raw_budget_fixture()
    normalized = normalize_budget_sheet(raw)
    profile = enrich_profile(
        {
            "rows": len(normalized),
            "columns": len(normalized.columns),
            "column_names": normalized.columns.tolist(),
            "likely_amount_columns": ["당년도예산"],
            "likely_name_columns": ["비용명"],
            "likely_category_columns": ["비목분류"],
            "unnamed_columns": [],
            "missing_counts": {},
            "sample_values_by_column": {},
        },
        "budget_comparison",
    )
    assert profile["domain"] == "budget_comparison"
    assert profile["is_budget_table"] is True
    assert "당해예산" in profile["domain_synonyms"]
    assert profile["domain_example_queries"]


def test_enrich_profile_generic_has_no_budget_examples() -> None:
    profile = enrich_profile(
        {
            "rows": 2,
            "columns": 2,
            "column_names": ["이름", "매출"],
            "likely_amount_columns": ["매출"],
            "likely_name_columns": ["이름"],
            "likely_category_columns": [],
            "unnamed_columns": [],
            "missing_counts": {},
            "sample_values_by_column": {},
        },
        "generic",
    )
    assert profile["domain"] == "generic"
    assert profile["domain_synonyms"] == {}
    assert profile["domain_example_queries"] == []
    assert profile.get("domain_describe_label") is None


def test_detect_flat_budget_columns_use_budget_pack() -> None:
    cols = ["비목분류", "비용명", "당년도예산", "당년도집행"]
    assert get_pack(infer_domain_from_columns(cols)).name == "budget_comparison"
