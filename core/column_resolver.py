"""Fuzzy column name resolution for natural-language Excel queries."""

from __future__ import annotations

import difflib
import re

import pandas as pd


def _synonyms(profile: dict) -> dict[str, str]:
    return profile.get("domain_synonyms") or {}


def _normalize(name: str) -> str:
    return re.sub(r"\s+", "", str(name)).lower()


def _candidate_columns(df: pd.DataFrame, profile: dict) -> list[str]:
    unnamed = set(profile.get("unnamed_columns", []))
    preferred = [c for c in df.columns.astype(str).tolist() if c not in unnamed]
    return preferred or df.columns.astype(str).tolist()


_FORMULA_OP_PATTERN = re.compile(r"[/\*\+]|(?<=\s)-(?=\s)")
_FORMULA_COLUMN_ERROR = "수식은 컬럼명으로 사용할 수 없습니다. 파생 컬럼(derive)을 사용하세요."


def _looks_like_formula(expr: str) -> bool:
    return bool(_FORMULA_OP_PATTERN.search(expr))


def _format_candidates(candidates: list[str], limit: int = 5) -> str:
    shown = candidates[:limit]
    text = ", ".join(shown)
    if len(candidates) > limit:
        text += f" 외 {len(candidates) - limit}개"
    return text


def resolve_column(user_expression: str, df: pd.DataFrame, profile: dict) -> str:
    """Resolve a user-mentioned column to an actual DataFrame column name."""
    if not user_expression or not str(user_expression).strip():
        raise ValueError("컬럼명이 비어 있습니다.")

    user_col = str(user_expression).strip()
    columns = df.columns.astype(str).tolist()
    candidates = _candidate_columns(df, profile)

    if user_col in columns:
        return user_col

    user_norm = _normalize(user_col)
    for col in columns:
        if _normalize(col) == user_norm:
            return col

    if _looks_like_formula(user_col):
        raise ValueError(_FORMULA_COLUMN_ERROR)

    canonical = _synonyms(profile).get(user_col) or _synonyms(profile).get(user_norm)
    if canonical:
        if canonical in columns:
            return canonical
        for col in candidates:
            if canonical in col or col in canonical:
                return col

    for col in candidates:
        col_norm = _normalize(col)
        if user_norm in col_norm or col_norm in user_norm:
            return col

    for expr, target in _synonyms(profile).items():
        if expr in user_col or user_col in expr:
            if target in columns:
                return target
            for col in candidates:
                if target in col:
                    return col

    matches = difflib.get_close_matches(user_col, candidates, n=1, cutoff=0.45)
    if matches:
        return matches[0]

    norm_map = {_normalize(c): c for c in candidates}
    norm_matches = difflib.get_close_matches(user_norm, list(norm_map), n=1, cutoff=0.6)
    if norm_matches:
        return norm_map[norm_matches[0]]

    raise ValueError(
        f"'{user_col}'에 해당하는 컬럼을 찾지 못했습니다. "
        f"사용 가능한 유사 컬럼: {_format_candidates(candidates)}"
    )


def resolve_columns(user_columns: list[str], df: pd.DataFrame, profile: dict) -> list[str]:
    """Resolve a list of user-mentioned columns."""
    return [resolve_column(col, df, profile) for col in user_columns]


def suggest_columns(user_expression: str, df: pd.DataFrame, profile: dict, n: int = 5) -> list[str]:
    """Return top column name suggestions for a user expression."""
    candidates = _candidate_columns(df, profile)
    user_norm = _normalize(user_expression)
    matches = difflib.get_close_matches(user_expression, candidates, n=n, cutoff=0.3)
    if not matches:
        matches = difflib.get_close_matches(user_norm, [_normalize(c) for c in candidates], n=n, cutoff=0.3)
        norm_map = {_normalize(c): c for c in candidates}
        matches = [norm_map[m] for m in matches if m in norm_map]
    return matches[:n]
