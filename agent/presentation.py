"""User-facing Korean markdown and message formatting."""

from __future__ import annotations

import pandas as pd

from core.operations import describe_dataset_info


def analysis_examples(profile: dict) -> list[str]:
    domain_examples = profile.get("domain_example_queries") or []
    if domain_examples:
        return [f'"{q}"' if not q.startswith('"') else q for q in domain_examples]

    name_col = profile.get("likely_name_columns", ["항목"])
    amount_col = profile.get("likely_amount_columns", ["금액"])
    cat_col = profile.get("likely_category_columns", [])
    examples = [
        f'"{amount_col[0]}이 가장 높은 행 찾아줘"',
        f'"{name_col[0]}가 얼마야?"',
    ]
    if cat_col:
        examples.append(f'"{cat_col[0]}별 {amount_col[0]} 합계 보여줘"')
    examples.append('"데이터에 대해서 설명"')
    return examples


def build_help_message(profile: dict | None = None) -> str:
    """Build profile-aware help message with question examples."""
    profile = profile or {}
    lines = [
        "업로드된 엑셀 파일을 기준으로 아래와 같은 질문을 할 수 있습니다.",
        "",
        "**데이터 이해**",
        '- "데이터에 대해서 설명"',
        '- "니가 할 수 있는게 뭐야"',
        "",
        "**항목/금액 조회**",
    ]
    name_col = profile.get("likely_name_columns") or [profile.get("domain_help_item_fallback", "항목")]
    amount_cols = profile.get("likely_amount_columns") or [profile.get("domain_help_amount_fallback", "금액")]
    name_example = name_col[0] if name_col else profile.get("domain_help_item_fallback", "항목")
    amount_example = amount_cols[0] if amount_cols else profile.get("domain_help_amount_fallback", "금액")
    samples = profile.get("sample_values_by_column", {}).get(name_example, [])
    item_example = samples[0] if samples else name_example

    lines.extend(
        [
            f'- "{item_example}가 얼마야?"',
            f'- "{amount_example}이 가장 높은 행 찾아줘"',
            '- "잔액이 남은 항목 보여줘"',
        ]
    )

    cat_col = profile.get("likely_category_columns", [])
    if cat_col:
        lines.extend(
            [
                "",
                "**집계/정렬/필터**",
                f'- "{cat_col[0]}별 {amount_example} 합계 보여줘"',
                f'- "{amount_example} 기준으로 큰 순서대로 보여줘"',
                f'- "{amount_example}이 0보다 큰 항목만 보여줘"',
            ]
        )

    lines.extend(["", "**팁**"])
    if profile.get("domain_synonym_tip"):
        lines.append(f"- {profile['domain_synonym_tip']}")
    lines.append("- 모든 숫자는 pandas로 실제 계산한 결과입니다.")
    return "\n".join(lines)


HELP_MESSAGE = build_help_message()


def describe_dataset(df: pd.DataFrame, profile: dict) -> str:
    """Build a natural-language summary of the dataset."""
    if profile.get("domain_describe_label"):
        amount_cols = profile.get("likely_amount_columns", [])
        name_cols = profile.get("domain_name_columns") or profile.get("likely_name_columns", [])
        label = profile["domain_describe_label"]
        key_cols = ", ".join(f"`{c}`" for c in name_cols[:3]) if name_cols else "주요 식별 컬럼"
        return (
            f"이 파일은 **{label}** 형식의 예산·집행 현황 데이터입니다.\n\n"
            f"- **{profile['rows']}행**, **{profile['columns']}열**\n"
            f"- 주요 기준 컬럼: {key_cols}\n"
            f"- 주요 금액 컬럼: {', '.join(f'`{c}`' for c in amount_cols[:8])}\n"
            "- 기본 분석은 **상세 항목**만 대상으로 합니다.\n"
            "- '전체 합계 알려줘'처럼 질문하면 합계 행을 사용합니다.\n\n"
            "**질문 예시**\n"
            + "\n".join(f'- "{q}"' for q in profile.get("domain_example_queries", [])[:3])
        )

    info = describe_dataset_info(df, profile)
    examples = analysis_examples(profile)
    lines = [
        f"이 데이터는 **{info['rows']}행**, **{info['columns']}열**로 구성되어 있습니다.",
        "",
        "**주요 컬럼**",
        ", ".join(f"`{c}`" for c in info["column_names"][:12]),
    ]
    if info["likely_amount_columns"]:
        lines.extend(["", "**금액/예산 관련 컬럼**", ", ".join(f"`{c}`" for c in info["likely_amount_columns"])])
    if info["likely_category_columns"]:
        lines.extend(["", "**분류 컬럼**", ", ".join(f"`{c}`" for c in info["likely_category_columns"])])
    if info["likely_name_columns"]:
        lines.extend(["", "**항목/이름 컬럼**", ", ".join(f"`{c}`" for c in info["likely_name_columns"])])
    if info["unnamed_columns"]:
        lines.extend(["", "**Unnamed 컬럼**", f"{len(info['unnamed_columns'])}개 (분석 시 우선순위 낮음)"])
    lines.extend(
        [
            "",
            "**결측치**",
            "없음" if not info["missing_counts"] else str(len(info["missing_counts"])) + "개 컬럼에 결측 존재",
        ]
    )
    lines.extend(["", "**이 데이터로 해볼 수 있는 질문 예시**"])
    lines.extend([f"- {ex}" for ex in examples])
    return "\n".join(lines)
