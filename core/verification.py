"""Post-operation invariant checks for DataFrame results."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import pandas as pd

from core.operations import exclude_summary_rows

_TOLERANCE = 1e-6

_REGISTERED_OPS = frozenset({
    "filter",
    "sort",
    "aggregate",
    "top_n",
    "derive",
    "select",
    "exclude_summary",
})


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class VerificationReport:
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def summary(self) -> str:
        if not self.checks:
            return "검사 없음"
        failed = [c for c in self.checks if not c.passed]
        if not failed:
            return f"{len(self.checks)}개 검사 모두 통과"
        return f"{len(failed)}개 검사 실패: {failed[0].name} — {failed[0].detail}"

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "summary": self.summary(),
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail}
                for c in self.checks
            ],
        }


def _report_unregistered(op_type: str) -> VerificationReport:
    return VerificationReport(
        checks=[
            Check(
                name="등록 여부",
                passed=True,
                detail=f"'{op_type}' 연산은 불변식 검사가 정의되지 않아 검사를 건너뜁니다.",
            )
        ]
    )


def _row_multiset(df: pd.DataFrame, columns: list[str]) -> Counter:
    tuples = [tuple(row) for row in df[columns].itertuples(index=False, name=None)]
    return Counter(tuples)


def _is_row_subset(input_df: pd.DataFrame, output_df: pd.DataFrame) -> bool:
    if output_df.empty:
        return True
    common_cols = [col for col in output_df.columns if col in input_df.columns]
    if not common_cols:
        return False
    input_counts = _row_multiset(input_df, common_cols)
    output_counts = _row_multiset(output_df, common_cols)
    return all(input_counts[row] >= count for row, count in output_counts.items())


def _numeric_series(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _verify_filter(input_df: pd.DataFrame, output_df: pd.DataFrame, op_args: dict) -> VerificationReport:
    checks = [
        Check(
            name="행수 보존(감소만)",
            passed=len(output_df) <= len(input_df),
            detail=f"입력 {len(input_df)}행 → 출력 {len(output_df)}행",
        ),
        Check(
            name="컬럼 보존",
            passed=list(output_df.columns) == list(input_df.columns),
            detail=f"입력 컬럼 {list(input_df.columns)} / 출력 컬럼 {list(output_df.columns)}",
        ),
    ]
    return VerificationReport(checks=checks)


def _verify_sort(input_df: pd.DataFrame, output_df: pd.DataFrame, op_args: dict) -> VerificationReport:
    checks: list[Check] = [
        Check(
            name="행수 보존",
            passed=len(output_df) == len(input_df),
            detail=f"{len(input_df)}행 → {len(output_df)}행",
        ),
        Check(
            name="컬럼 보존",
            passed=list(output_df.columns) == list(input_df.columns),
            detail=f"컬럼 수 {len(input_df.columns)} → {len(output_df.columns)}",
        ),
    ]
    column = op_args.get("column", "")
    if column in input_df.columns and column in output_df.columns and len(output_df) > 1:
        values = _numeric_series(output_df[column]).dropna()
        ascending = op_args.get("ascending", True)
        if len(values) > 1:
            diffs = values.diff().dropna()
            if ascending:
                monotone = bool((diffs >= -_TOLERANCE).all())
            else:
                monotone = bool((diffs <= _TOLERANCE).all())
            checks.append(
                Check(
                    name="정렬 단조성",
                    passed=monotone,
                    detail=f"'{column}' 기준 {'오름차순' if ascending else '내림차순'}",
                )
            )
    multiset_ok = True
    for col in input_df.columns:
        if col not in output_df.columns:
            continue
        in_num = _numeric_series(input_df[col]).dropna().sort_values().tolist()
        out_num = _numeric_series(output_df[col]).dropna().sort_values().tolist()
        if in_num and out_num and in_num != out_num:
            in_text = sorted(input_df[col].astype(str).tolist())
            out_text = sorted(output_df[col].astype(str).tolist())
            if in_text != out_text:
                multiset_ok = False
                break
    checks.append(
        Check(
            name="값 멀티셋 보존",
            passed=multiset_ok,
            detail="정렬 전후 값 구성이 동일해야 합니다.",
        )
    )
    return VerificationReport(checks=checks)


def _verify_aggregate(input_df: pd.DataFrame, output_df: pd.DataFrame, op_args: dict) -> VerificationReport:
    group_by = op_args.get("group_by") or []
    agg_col = op_args.get("agg_column", "")
    agg_func = op_args.get("agg_func", "sum")
    checks: list[Check] = []

    if group_by and all(col in input_df.columns for col in group_by):
        max_groups = input_df.groupby(group_by, dropna=False).ngroups
        checks.append(
            Check(
                name="그룹 수 상한",
                passed=len(output_df) <= max_groups,
                detail=f"출력 {len(output_df)}그룹 / 입력 고유 {max_groups}그룹",
            )
        )

    if agg_func == "sum" and agg_col in input_df.columns:
        sum_col = f"{agg_col}_sum" if f"{agg_col}_sum" in output_df.columns else agg_col
        if sum_col in output_df.columns:
            input_sum = _numeric_series(input_df[agg_col]).sum()
            output_sum = _numeric_series(output_df[sum_col]).sum()
            input_missing = input_df[agg_col].isna().sum()
            if input_missing == 0:
                checks.append(
                    Check(
                        name="합계 보존",
                        passed=abs(float(input_sum) - float(output_sum)) <= _TOLERANCE,
                        detail=f"입력 합 {input_sum} / 그룹 합계 합 {output_sum}",
                    )
                )
    return VerificationReport(checks=checks)


def _verify_top_n(input_df: pd.DataFrame, output_df: pd.DataFrame, op_args: dict) -> VerificationReport:
    n = int(op_args.get("n", 1))
    expected_rows = min(n, len(input_df))
    checks = [
        Check(
            name="행수",
            passed=len(output_df) == expected_rows,
            detail=f"기대 {expected_rows}행, 실제 {len(output_df)}행",
        ),
    ]
    if not output_df.empty and not input_df.empty:
        checks.append(
            Check(
                name="부분집합",
                passed=_is_row_subset(input_df, output_df),
                detail="결과 행이 입력의 부분집합이어야 합니다.",
            )
        )
    return VerificationReport(checks=checks)


def _verify_derive(input_df: pd.DataFrame, output_df: pd.DataFrame, op_args: dict) -> VerificationReport:
    new_column = op_args.get("new_column", "")
    checks = [
        Check(
            name="행수 보존",
            passed=len(output_df) == len(input_df),
            detail=f"{len(input_df)}행 → {len(output_df)}행",
        ),
    ]
    for col in input_df.columns:
        if col not in output_df.columns:
            checks.append(
                Check(name=f"컬럼 '{col}' 보존", passed=False, detail="기존 컬럼이 누락되었습니다.")
            )
            continue
        same = input_df[col].equals(output_df[col])
        checks.append(
            Check(
                name=f"컬럼 '{col}' 값 불변",
                passed=same,
                detail="기존 컬럼 값이 변경되었습니다." if not same else "동일",
            )
        )
    if new_column:
        checks.append(
            Check(
                name="신규 컬럼 추가",
                passed=new_column in output_df.columns,
                detail=f"'{new_column}' 컬럼 존재 여부",
            )
        )
    return VerificationReport(checks=checks)


def _verify_select(input_df: pd.DataFrame, output_df: pd.DataFrame, op_args: dict) -> VerificationReport:
    checks = [
        Check(
            name="행수 보존",
            passed=len(output_df) == len(input_df),
            detail=f"{len(input_df)}행 → {len(output_df)}행",
        ),
        Check(
            name="컬럼 부분집합",
            passed=set(output_df.columns).issubset(set(input_df.columns)),
            detail=f"출력 컬럼 {list(output_df.columns)}",
        ),
    ]
    return VerificationReport(checks=checks)


def _verify_exclude_summary(input_df: pd.DataFrame, output_df: pd.DataFrame, op_args: dict) -> VerificationReport:
    profile = op_args.get("_profile") or {}
    expected = exclude_summary_rows(input_df, profile)
    expected_removed = len(input_df) - len(expected)
    actual_removed = len(input_df) - len(output_df)
    checks = [
        Check(
            name="제거 행수 일치",
            passed=actual_removed == expected_removed,
            detail=f"기대 제거 {expected_removed}행, 실제 제거 {actual_removed}행",
        ),
        Check(
            name="컬럼 보존",
            passed=list(output_df.columns) == list(input_df.columns),
            detail="컬럼 구성이 동일해야 합니다.",
        ),
    ]
    return VerificationReport(checks=checks)


_VERIFIERS = {
    "filter": _verify_filter,
    "sort": _verify_sort,
    "aggregate": _verify_aggregate,
    "top_n": _verify_top_n,
    "derive": _verify_derive,
    "select": _verify_select,
    "exclude_summary": _verify_exclude_summary,
}


def verify_operation(
    op_type: str,
    input_df: pd.DataFrame,
    output_df: pd.DataFrame,
    op_args: dict,
) -> VerificationReport:
    """Run invariant checks for a single operation."""
    if op_type not in _REGISTERED_OPS:
        return _report_unregistered(op_type)
    verifier = _VERIFIERS[op_type]
    return verifier(input_df, output_df, op_args or {})
