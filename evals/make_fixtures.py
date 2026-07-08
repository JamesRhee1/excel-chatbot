"""Generate synthetic Excel fixtures for the evaluation harness."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _budget_raw_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            [
                "비목분류",
                "",
                "비용명",
                "계획예산",
                "실행예산",
                "실행예산",
                "실행예산",
                "전년도집행",
                "당년도예산",
                "당년도집행",
                "가집행금액",
                "당해누계",
                "집행계",
                "집행계",
                "집행계",
                "예산잔액",
                "예산잔액",
                "예산잔액",
            ],
            [
                "",
                "",
                "",
                "",
                "이월예산",
                "당해예산",
                "합계",
                "",
                "",
                "",
                "",
                "",
                "이월집행",
                "당해집행",
                "합계",
                "이월잔액",
                "당해잔액",
                "합계",
            ],
            ["연구개발비", "30101", "인쇄비", 1000, 100, 200, 300, 50, 3_000_000, 0, 200_000, 0, 0, 0, 0, 0, 0, 2_800_000],
            ["", "30102", "회의비", 2000, 200, 400, 600, 100, 5_000_000, 1000, 500_000, 500, 0, 500, 500, 0, 4_500_000, 4_500_000],
            ["소 계", "", "", 3000, 300, 600, 900, 150, 8_000_000, 1000, 700_000, 500, 0, 500, 500, 0, 4_500_000, 4_500_000],
            ["합         계", "", "", 3000, 300, 600, 900, 150, 150_000_000, 1000, 700_000, 500, 0, 500, 500, 0, 4_500_000, 4_500_000],
        ]
    )


def _generic_sales_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "이름": ["김철수", "이영희", "박민수", "최지연", "한서준"],
            "부서": ["영업", "개발", "영업", "개발", "마케팅"],
            "매출": [1000, 2500, 800, 3200, 1500],
            "연도": [2023, 2023, 2024, 2024, 2023],
        }
    )


def make_fixtures(target_dir: Path | None = None) -> None:
    out = target_dir or FIXTURES_DIR
    out.mkdir(parents=True, exist_ok=True)
    _budget_raw_frame().to_excel(out / "budget_comparison.xlsx", index=False, header=False)
    _generic_sales_frame().to_excel(out / "generic_sales.xlsx", index=False)


if __name__ == "__main__":
    make_fixtures()
