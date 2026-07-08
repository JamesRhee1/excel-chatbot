"""Budget comparison (예실대비표) domain pack."""

from __future__ import annotations

import re

import pandas as pd

from domains.base import DomainPack, SummaryRowConfig

OUTPUT_COLUMNS = [
    "행구분",
    "비목분류",
    "비목코드",
    "비용명",
    "계획예산",
    "실행예산_이월예산",
    "실행예산_당해예산",
    "실행예산_합계",
    "전년도집행",
    "당년도예산",
    "당년도집행",
    "가집행금액",
    "당해누계",
    "집행계_이월집행",
    "집행계_당해집행",
    "집행계_합계",
    "예산잔액_이월잔액",
    "예산잔액_당해잔액",
    "예산잔액_합계",
]

_ROW0_MARKERS = ("비목분류", "비용명", "계획예산", "실행예산", "전년도집행", "당년도예산", "집행계", "예산잔액")
_ROW1_MARKERS = ("이월예산", "당해예산", "합계", "이월집행", "당해집행", "이월잔액", "당해잔액")

_HEADER_ALIASES: dict[str, str] = {
    "계획예산": "계획예산",
    "전년도집행": "전년도집행",
    "당년도예산": "당년도예산",
    "당년도집행": "당년도집행",
    "가집행금액": "가집행금액",
    "당해누계": "당해누계",
    "실행예산_이월예산": "실행예산_이월예산",
    "실행예산_당해예산": "실행예산_당해예산",
    "실행예산_합계": "실행예산_합계",
    "집행계_이월집행": "집행계_이월집행",
    "집행계_당해집행": "집행계_당해집행",
    "집행계_합계": "집행계_합계",
    "예산잔액_이월잔액": "예산잔액_이월잔액",
    "예산잔액_당해잔액": "예산잔액_당해잔액",
    "예산잔액_합계": "예산잔액_합계",
}

BUDGET_SYNONYMS: dict[str, str] = {
    "당해예산": "당년도예산",
    "올해예산": "당년도예산",
    "금년예산": "당년도예산",
    "올해 예산": "당년도예산",
    "당년예산": "당년도예산",
    "당해집행": "당년도집행",
    "올해집행": "당년도집행",
    "금년집행": "당년도집행",
    "작년집행": "전년도집행",
    "전년집행": "전년도집행",
    "잔액": "예산잔액_당해잔액",
    "남은예산": "예산잔액_당해잔액",
    "남은 금액": "예산잔액_당해잔액",
    "예산잔액": "예산잔액_합계",
    "비용": "비용명",
    "항목": "비용명",
    "항목명": "비용명",
    "무엇": "비용명",
    "이름": "비용명",
    "분류": "비목분류",
    "구분": "비목분류",
    "총액": "집행계",
    "합계": "집행계",
    "계획": "계획예산",
    "실행": "실행예산",
}


def _cell_str(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return re.sub(r"\s+", " ", str(value).strip())


def _compact(value) -> str:
    return re.sub(r"\s+", "", _cell_str(value))


def detect_budget_sheet(df_raw: pd.DataFrame) -> bool:
    """Detect 예실대비표-style 2-row header sheets."""
    if df_raw is None or len(df_raw) < 3 or df_raw.shape[1] < 8:
        return False
    row0_text = " ".join(_cell_str(v) for v in df_raw.iloc[0].tolist())
    row1_text = " ".join(_cell_str(v) for v in df_raw.iloc[1].tolist())
    row0_hits = sum(1 for marker in _ROW0_MARKERS if marker in row0_text)
    row1_hits = sum(1 for marker in _ROW1_MARKERS if marker in row1_text)
    return row0_hits >= 3 and row1_hits >= 2


def _forward_fill_header(values: list[str]) -> list[str]:
    filled: list[str] = []
    last = ""
    for value in values:
        if value:
            last = value
        filled.append(last)
    return filled


def _build_amount_column_names(row0: pd.Series, row1: pd.Series, start_col: int = 3) -> list[str]:
    parents = _forward_fill_header([_cell_str(v) for v in row0.tolist()])
    children = [_cell_str(v) for v in row1.tolist()]
    names: list[str] = []
    for idx in range(start_col, len(row0)):
        parent = parents[idx]
        child = children[idx]
        if parent and child:
            raw = f"{parent}_{child}"
        elif parent:
            raw = parent
        elif child:
            raw = child
        else:
            raw = f"col_{idx}"
        names.append(_canonical_amount_name(parent, child, raw))
    return names


def _canonical_amount_name(parent: str, child: str, raw: str) -> str:
    compact_raw = _compact(raw)
    for key, canonical in _HEADER_ALIASES.items():
        if _compact(key) == compact_raw or key in raw:
            return canonical

    parent_c = _compact(parent)
    child_c = _compact(child)

    if parent_c == "실행예산":
        if "이월" in child_c:
            return "실행예산_이월예산"
        if "당해" in child_c:
            return "실행예산_당해예산"
        if "합계" in child_c:
            return "실행예산_합계"
    if parent_c == "집행계":
        if "이월" in child_c:
            return "집행계_이월집행"
        if "당해" in child_c:
            return "집행계_당해집행"
        if "합계" in child_c:
            return "집행계_합계"
    if parent_c == "예산잔액":
        if "이월" in child_c:
            return "예산잔액_이월잔액"
        if "당해" in child_c:
            return "예산잔액_당해잔액"
        if "합계" in child_c:
            return "예산잔액_합계"

    if parent_c in _HEADER_ALIASES:
        return _HEADER_ALIASES[parent_c]
    if compact_raw in {_compact(k) for k in _HEADER_ALIASES}:
        for key, canonical in _HEADER_ALIASES.items():
            if _compact(key) == compact_raw:
                return canonical

    return raw.replace(" ", "_")


def _classify_row_type(col_a: str, current_category: str) -> tuple[str, str]:
    text = _cell_str(col_a)
    compact = _compact(col_a)

    if compact == "소계" or text == "소 계":
        return "소계", current_category
    if compact == "내부흡수액":
        return "내부흡수액", current_category
    if compact == "외부유출액":
        return "외부유출액", current_category
    if compact == "합계" or text.startswith("합") and "계" in compact:
        return "합계", text or current_category
    if text:
        return "상세", text
    return "상세", current_category


def _to_numeric(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("원", "", regex=False)
        .str.strip()
        .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
    )
    return pd.to_numeric(cleaned, errors="coerce")


def normalize_budget_sheet(df_raw: pd.DataFrame) -> pd.DataFrame:
    """Convert raw header=None 예실대비표 into a normalized analysis DataFrame."""
    if df_raw is None or df_raw.empty:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    work = df_raw.copy()
    amount_names = _build_amount_column_names(work.iloc[0], work.iloc[1], start_col=3)
    data = work.iloc[2:].reset_index(drop=True)

    records: list[dict] = []
    current_category = ""

    for _, row in data.iterrows():
        col_a = _cell_str(row.iloc[0]) if len(row) > 0 else ""
        col_b = _cell_str(row.iloc[1]) if len(row) > 1 else ""
        col_c = _cell_str(row.iloc[2]) if len(row) > 2 else ""

        row_type, category = _classify_row_type(col_a, current_category)
        if category:
            current_category = category

        cost_name = col_c or (col_b if row_type == "상세" and not col_a else "")
        if row_type == "상세" and not cost_name and col_b and not col_b.isdigit():
            cost_name = col_b

        if not any([col_a, col_b, col_c]) and not any(
            _cell_str(row.iloc[i]) for i in range(3, min(len(row), 3 + len(amount_names)))
        ):
            continue

        record: dict = {
            "행구분": row_type,
            "비목분류": current_category,
            "비목코드": col_b if row_type == "상세" else "",
            "비용명": cost_name,
        }

        for i, name in enumerate(amount_names):
            col_idx = 3 + i
            if col_idx < len(row):
                record[name] = row.iloc[col_idx]
            else:
                record[name] = pd.NA

        records.append(record)

    if not records:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    result = pd.DataFrame(records)

    for col in OUTPUT_COLUMNS:
        if col not in result.columns:
            result[col] = pd.NA

    result = result[OUTPUT_COLUMNS]
    result["비목분류"] = result["비목분류"].replace("", pd.NA)
    result["비목분류"] = result["비목분류"].ffill()
    result["비용명"] = result["비용명"].astype(str).str.strip().replace({"nan": "", "None": ""})
    result["비목코드"] = result["비목코드"].astype(str).str.strip().replace({"nan": "", "None": ""})

    for col in OUTPUT_COLUMNS[4:]:
        result[col] = _to_numeric(result[col])

    text_empty = result["비용명"].eq("") & result["비목코드"].eq("") & result["비목분류"].isna()
    amount_empty = result[OUTPUT_COLUMNS[4:]].isna().all(axis=1)
    result = result[~(text_empty & amount_empty)].reset_index(drop=True)

    return result


class BudgetComparisonPack(DomainPack):
    def __init__(self) -> None:
        super().__init__(
            name="budget_comparison",
            synonyms=dict(BUDGET_SYNONYMS),
            summary_row_config=SummaryRowConfig(
                row_type_column="행구분",
                detail_row_type="상세",
                total_row_types=("합계",),
                all_analysis_row_types=("상세", "소계", "합계", "내부흡수액", "외부유출액"),
            ),
            example_queries=(
                "당해예산 중 가장 높은 행 찾아줘",
                "인쇄비가 얼마지",
                "비목분류별 당년도예산 합계 보여줘",
            ),
            clarify_examples=(
                "'당년도예산이 가장 높은 행 찾아줘' (합계/소계 행은 자동 제외)",
                "'인쇄비가 얼마야?'",
                "'비목분류별 당년도예산 합계 보여줘'",
            ),
            compare_columns=(
                "당년도예산",
                "당년도집행",
                "예산잔액_당해잔액",
                "예산잔액_합계",
                "계획예산",
                "실행예산_당해예산",
                "실행예산_합계",
            ),
            name_columns=("비용명", "비목분류"),
            value_primary_cols=(
                "당년도예산",
                "당년도집행",
                "예산잔액_당해잔액",
                "예산잔액_합계",
            ),
            value_secondary_cols=(
                "계획예산",
                "실행예산_당해예산",
                "실행예산_합계",
                "집행계_합계",
            ),
            default_display_cols=(
                "비목분류",
                "비용명",
                "당년도예산",
                "당년도집행",
                "예산잔액_당해잔액",
                "예산잔액_합계",
            ),
            top_n_extra_cols=("당년도집행", "예산잔액_당해잔액", "예산잔액_합계"),
            column_labels={
                "당년도예산": "당년도예산",
                "당년도집행": "당년도집행",
                "예산잔액_당해잔액": "예산잔액",
                "예산잔액_합계": "예산잔액(합계)",
                "계획예산": "계획예산",
                "실행예산_당해예산": "실행예산",
                "실행예산_합계": "실행예산(합계)",
                "집행계_합계": "집행계",
            },
            multi_display_cols=(
                "비목분류",
                "비용명",
                "당년도예산",
                "당년도집행",
                "예산잔액_당해잔액",
                "예산잔액_합계",
                "집행률",
            ),
            multi_example_queries=(
                "파일별 당년도예산 합계 비교해줘",
                "인쇄비를 파일별로 비교해줘",
                "각 파일에서 당년도예산이 가장 높은 항목 알려줘",
                "전체 파일에서 예산잔액이 가장 큰 항목 5개 보여줘",
                "파일별 집행률 비교해줘",
            ),
            normalized_signature_columns=("행구분", "비목분류", "비용명"),
            help_item_fallback="비용명",
            help_amount_fallback="당년도예산",
            balance_column_fallback="예산잔액_당해잔액",
            synonym_tip='정확한 컬럼명을 몰라도 됩니다. "당해예산" → "당년도예산"처럼 자동 해석합니다.',
            describe_label="예실대비표",
            output_columns=tuple(OUTPUT_COLUMNS),
        )

    def detect(self, raw_df: pd.DataFrame) -> bool:
        return detect_budget_sheet(raw_df)

    def matches_normalized_columns(self, column_names: list[str]) -> bool:
        cols = set(column_names)
        if {"행구분", "비목분류", "비용명"}.issubset(cols):
            return True
        return {"비목분류", "비용명", "당년도예산"}.issubset(cols)

    def normalize_raw(
        self,
        raw_df: pd.DataFrame,
        *,
        path: str = "",
        sheet_name: str | int = 0,
    ) -> pd.DataFrame:
        return normalize_budget_sheet(raw_df)

    def add_derived_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        return add_budget_metrics(df)


BUDGET_COMPARISON_PACK = BudgetComparisonPack()

# Backward-compatible aliases
is_budget_comparison_sheet = detect_budget_sheet


def _safe_ratio(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denom = denominator.replace(0, pd.NA)
    result = numerator / denom
    return result.fillna(0)


def add_budget_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """Add budget derived columns without mutating the input DataFrame."""
    result = df.copy()

    if "당년도집행" in result.columns and "당년도예산" in result.columns:
        result["집행률"] = _safe_ratio(result["당년도집행"], result["당년도예산"])

    if "예산잔액_합계" in result.columns and "당년도예산" in result.columns:
        result["잔액률"] = _safe_ratio(result["예산잔액_합계"], result["당년도예산"])

    if "당년도예산" in result.columns and "당년도집행" in result.columns:
        result["예산대비집행차이"] = result["당년도예산"] - result["당년도집행"]

    return result
