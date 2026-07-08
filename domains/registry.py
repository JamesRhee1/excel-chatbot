"""Domain pack registry and profile enrichment."""

from __future__ import annotations

import pandas as pd

from domains.base import DomainPack
from domains.budget_comparison import BUDGET_COMPARISON_PACK
from domains.generic import GENERIC_PACK

_REGISTERED_PACKS: tuple[DomainPack, ...] = (BUDGET_COMPARISON_PACK, GENERIC_PACK)
_PACK_BY_NAME: dict[str, DomainPack] = {pack.name: pack for pack in _REGISTERED_PACKS}


def registered_packs() -> tuple[DomainPack, ...]:
    return _REGISTERED_PACKS


def get_pack(name: str) -> DomainPack:
    return _PACK_BY_NAME.get(name, GENERIC_PACK)


def apply_derived_metrics(df: pd.DataFrame, domain: str) -> pd.DataFrame:
    """Apply domain-pack derived columns via the registry."""
    return get_pack(domain).add_derived_metrics(df)


def match_pack(raw_df: pd.DataFrame) -> DomainPack:
    """Return the first pack whose detect() matches, else generic."""
    for pack in _REGISTERED_PACKS:
        if pack.name == "generic":
            continue
        if pack.detect(raw_df):
            return pack
    return GENERIC_PACK


def enrich_profile(profile: dict, domain: str) -> dict:
    """Attach domain metadata to a structural profile dict."""
    pack = get_pack(domain)
    result = dict(profile)
    result["domain"] = pack.name
    result["domain_synonyms"] = dict(pack.synonyms)
    result["summary_row_config"] = {
        "row_type_column": pack.summary_row_config.row_type_column,
        "detail_row_type": pack.summary_row_config.detail_row_type,
        "total_row_types": list(pack.summary_row_config.total_row_types),
        "all_analysis_row_types": list(pack.summary_row_config.all_analysis_row_types),
    }
    result["domain_example_queries"] = list(pack.example_queries)
    result["domain_clarify_examples"] = list(pack.clarify_examples)
    result["domain_compare_columns"] = list(pack.compare_columns)
    result["domain_name_columns"] = list(pack.name_columns)
    result["domain_help_item_fallback"] = pack.help_item_fallback
    result["domain_help_amount_fallback"] = pack.help_amount_fallback
    result["domain_balance_column_fallback"] = pack.balance_column_fallback
    result["domain_synonym_tip"] = pack.synonym_tip
    result["domain_describe_label"] = pack.describe_label
    result["domain_value_primary_cols"] = list(pack.value_primary_cols)
    result["domain_value_secondary_cols"] = list(pack.value_secondary_cols)
    result["domain_default_display_cols"] = list(pack.default_display_cols)
    result["domain_top_n_extra_cols"] = list(pack.top_n_extra_cols)
    result["domain_column_labels"] = dict(pack.column_labels)
    result["domain_multi_display_cols"] = list(pack.multi_display_cols)
    result["domain_multi_example_queries"] = list(pack.multi_example_queries)
    result["is_budget_table"] = pack.name == "budget_comparison"
    return result


def infer_domain_from_columns(column_names: list[str]) -> str:
    for pack in _REGISTERED_PACKS:
        if pack.name == "generic":
            continue
        if pack.matches_normalized_columns(column_names):
            return pack.name
    return "generic"
