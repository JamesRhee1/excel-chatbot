"""DataFrame profiling for adaptive Excel analysis."""

from __future__ import annotations

import pandas as pd

from domains.registry import enrich_profile, infer_domain_from_columns

_AMOUNT_KEYWORDS = (
    "예산", "금액", "비용", "집행", "잔액", "누계", "합계", "매출", "수량", "단가", "원가", "가집행",
)
_CATEGORY_KEYWORDS = ("분류", "구분", "유형", "카테고리", "부서", "지역", "비목", "과목", "계정")
_NAME_KEYWORDS = ("이름", "명", "비용명", "항목", "항목명", "품목", "제품", "사업명", "과제명")
_ID_LIKE_KEYWORDS = ("코드", "번호", "id", "no", "연도", "월", "일")


def _is_mostly_numeric(series: pd.Series) -> bool:
    if series.dropna().empty:
        return False
    numeric = pd.to_numeric(
        series.astype(str).str.replace(",", "", regex=False).str.strip(),
        errors="coerce",
    )
    return numeric.notna().sum() >= max(1, len(series.dropna()) * 0.5)


def _is_id_like_column(name: str) -> bool:
    lowered = str(name).strip().lower()
    return any(keyword in lowered for keyword in _ID_LIKE_KEYWORDS)


def profile_dataframe(df: pd.DataFrame, domain: str | None = None) -> dict:
    """Build a structural profile of a DataFrame for intent planning and routing."""
    column_names = [str(c) for c in df.columns.tolist()]
    unnamed_columns = [c for c in column_names if c.startswith("Unnamed")]

    numeric_columns = df.select_dtypes(include="number").columns.astype(str).tolist()
    text_columns = df.select_dtypes(include=["object", "string"]).columns.astype(str).tolist()
    datetime_columns = (
        df.select_dtypes(include=["datetime", "datetimetz"]).columns.astype(str).tolist()
    )

    missing_counts = {str(col): int(df[col].isna().sum()) for col in df.columns}

    sample_values_by_column: dict[str, list[str]] = {}
    for col in column_names:
        if col in unnamed_columns:
            continue
        samples = df[col].dropna().head(3).tolist()
        sample_values_by_column[col] = [str(v) for v in samples]

    likely_amount_columns: list[str] = []
    likely_category_columns: list[str] = []
    likely_name_columns: list[str] = []

    for col in column_names:
        if col in unnamed_columns:
            continue
        if _is_id_like_column(col):
            continue
        if col in numeric_columns or any(kw in col for kw in _AMOUNT_KEYWORDS):
            likely_amount_columns.append(col)
        elif col in text_columns and _is_mostly_numeric(df[col]):
            likely_amount_columns.append(col)
        if any(kw in col for kw in _CATEGORY_KEYWORDS):
            likely_category_columns.append(col)
        if any(kw in col for kw in _NAME_KEYWORDS):
            likely_name_columns.append(col)

    profile = {
        "rows": len(df),
        "columns": len(df.columns),
        "column_names": column_names,
        "numeric_columns": numeric_columns,
        "text_columns": text_columns,
        "datetime_columns": datetime_columns,
        "missing_counts": missing_counts,
        "sample_values_by_column": sample_values_by_column,
        "unnamed_columns": unnamed_columns,
        "likely_amount_columns": likely_amount_columns,
        "likely_category_columns": likely_category_columns,
        "likely_name_columns": likely_name_columns,
    }
    resolved_domain = domain or infer_domain_from_columns(column_names)
    return enrich_profile(profile, resolved_domain)
