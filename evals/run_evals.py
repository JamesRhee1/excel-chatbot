#!/usr/bin/env python3
"""Run golden-query evaluation against executor.run()."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from agent.executor import run

EVALS_DIR = Path(__file__).resolve().parent
FIXTURES_DIR = EVALS_DIR / "fixtures"
GOLDEN_PATH = EVALS_DIR / "golden_queries.yaml"


def _route_matches(actual: str, expected: str) -> bool:
    if expected == "rule":
        return actual == "rule"
    return actual in {"llm", "llm_fallback_clarify"}


def _op_types(operations: list[dict]) -> list[str]:
    return [op.get("type", "") for op in operations]


def _check_answer(result: dict, spec: dict | None) -> bool:
    if not spec:
        return True
    if not result.get("success"):
        return False

    if "row_count" in spec:
        df = result.get("raw_df")
        if df is None:
            df = result.get("df")
        if df is None:
            return False
        return len(df) == int(spec["row_count"])

    if "scalar" in spec:
        message = result.get("message") or ""
        target = str(spec["scalar"])
        return target in message.replace(",", "")

    cell = spec.get("cell")
    if cell:
        df = result.get("raw_df") or result.get("df")
        if df is None or df.empty:
            return False
        column = cell["column"]
        if column not in df.columns:
            return False
        if "row_index" in cell:
            value = df.iloc[int(cell["row_index"])][column]
        else:
            value = df[column].iloc[0]
        if isinstance(value, float):
            return abs(float(value) - float(cell["value"])) < 1e-6
        return str(value) == str(cell["value"])

    return True


def _verification_passed(result: dict) -> bool:
    reports = result.get("verification") or []
    if not reports:
        return True
    return all(report.get("passed", True) for report in reports)


def evaluate_query(item: dict, *, no_llm: bool) -> dict:
    expected_route = item["expected_route"]
    if no_llm and expected_route == "llm":
        return {
            "id": item["id"],
            "skipped": True,
            "route_ok": None,
            "ops_ok": None,
            "answer_ok": None,
            "verification_ok": None,
        }

    fixture = FIXTURES_DIR / item["fixture"]
    result = run(file_path=str(fixture), user_message=item["query"])
    actual_route = result.get("route_path", "")
    actual_ops = _op_types(result.get("operations") or [])
    expected_ops = list(item.get("expected_ops") or [])

    return {
        "id": item["id"],
        "skipped": False,
        "success": result.get("success", False),
        "route_ok": _route_matches(actual_route, expected_route),
        "ops_ok": actual_ops == expected_ops,
        "answer_ok": _check_answer(result, item.get("expected_answer")),
        "verification_ok": _verification_passed(result),
        "actual_route": actual_route,
        "actual_ops": actual_ops,
        "expected_ops": expected_ops,
        "error": result.get("error"),
    }


def _print_table(results: list[dict]) -> None:
    headers = ("ID", "라우팅", "연산", "답변", "검증", "비고")
    rows = []
    for row in results:
        if row.get("skipped"):
            rows.append((row["id"], "-", "-", "-", "-", "건너뜀"))
            continue
        note = row.get("error") or ""
        if not row.get("success"):
            note = note or "실행 실패"
        rows.append(
            (
                row["id"],
                "✓" if row["route_ok"] else "✗",
                "✓" if row["ops_ok"] else "✗",
                "✓" if row["answer_ok"] else "✗",
                "✓" if row["verification_ok"] else "✗",
                note,
            )
        )

    widths = [max(len(str(row[i])) for row in ([headers] + rows)) for i in range(len(headers))]
    line = " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
    print(line)
    print("-+-".join("-" * w for w in widths))
    for row in rows:
        print(" | ".join(str(row[i]).ljust(widths[i]) for i in range(len(headers))))


def _aggregate(results: list[dict]) -> dict:
    active = [r for r in results if not r.get("skipped")]
    if not active:
        return {
            "total": 0,
            "skipped": len(results),
            "route_accuracy": 0.0,
            "ops_accuracy": 0.0,
            "answer_accuracy": 0.0,
            "verification_pass_rate": 0.0,
        }
    return {
        "total": len(active),
        "skipped": len(results) - len(active),
        "route_accuracy": sum(1 for r in active if r["route_ok"]) / len(active),
        "ops_accuracy": sum(1 for r in active if r["ops_ok"]) / len(active),
        "answer_accuracy": sum(1 for r in active if r["answer_ok"]) / len(active),
        "verification_pass_rate": sum(1 for r in active if r["verification_ok"]) / len(active),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Golden-query evaluation harness")
    parser.add_argument("--no-llm", action="store_true", help="Skip queries that require the LLM route")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero unless every active query passes all checks at 100%",
    )
    parser.add_argument("--golden", type=Path, default=GOLDEN_PATH, help="Path to golden_queries.yaml")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path")
    args = parser.parse_args(argv)

    if not FIXTURES_DIR.exists():
        from evals.make_fixtures import make_fixtures

        make_fixtures(FIXTURES_DIR)

    payload = yaml.safe_load(args.golden.read_text(encoding="utf-8"))
    items = payload.get("queries") or []
    results = [evaluate_query(item, no_llm=args.no_llm) for item in items]
    summary = _aggregate(results)

    print("골든 질의 평가 결과")
    _print_table(results)
    print()
    print(
        f"실행 {summary['total']}건 / 건너뜀 {summary['skipped']}건 | "
        f"라우팅 {summary['route_accuracy']:.0%} | "
        f"연산 {summary['ops_accuracy']:.0%} | "
        f"답변 {summary['answer_accuracy']:.0%} | "
        f"검증 {summary['verification_pass_rate']:.0%}"
    )

    out_path = args.output
    if out_path is None:
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        out_path = EVALS_DIR / f"results_{day}.json"
    out_path.write_text(
        json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"결과 저장: {out_path}")

    failed = [
        r
        for r in results
        if not r.get("skipped")
        and not all([r.get("route_ok"), r.get("ops_ok"), r.get("answer_ok"), r.get("verification_ok")])
    ]
    exit_code = 1 if failed else 0
    if args.strict and exit_code == 0:
        active = [r for r in results if not r.get("skipped")]
        if args.no_llm:
            expected_rule = sum(1 for item in items if item.get("expected_route") == "rule")
            if len(active) != expected_rule:
                print(
                    f"STRICT 실패: 규칙 경로 {expected_rule}건 기대, 실제 실행 {len(active)}건",
                    file=sys.stderr,
                )
                exit_code = 1
        if exit_code == 0 and (
            summary["route_accuracy"] < 1.0
            or summary["ops_accuracy"] < 1.0
            or summary["answer_accuracy"] < 1.0
            or summary["verification_pass_rate"] < 1.0
        ):
            print("STRICT 실패: 일부 지표가 100%가 아닙니다.", file=sys.stderr)
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
