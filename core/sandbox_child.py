"""Isolated sandbox child process — invoked only via `python -I sandbox_child.py`.

Static pattern checks in the parent/child are auxiliary guards only.
The primary safety boundary is separate process execution with no shared namespace.
"""

from __future__ import annotations

import json
import platform
import resource
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Mirror parent denylist (auxiliary — isolation is the real safeguard).
_DANGEROUS_SUBSTRINGS = (
    "import os",
    "import sys",
    "import subprocess",
    "import socket",
    "import requests",
    "open(",
    "eval(",
    "exec(",
    "__import__",
)


def _validate_code(code: str) -> None:
    lowered = code.lower()
    for token in _DANGEROUS_SUBSTRINGS:
        if token in lowered:
            raise ValueError(f"허용되지 않는 코드 패턴: {token}")


def _apply_memory_limit(memory_limit_gb: float) -> None:
    if platform.system() == "Windows":
        return
    limit = int(memory_limit_gb * 1024 * 1024 * 1024)
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))


def _load_dataframe(path: Path) -> pd.DataFrame:
    return pd.read_json(path, orient="split")


def _save_dataframe(df: pd.DataFrame, path: Path) -> None:
    df.to_json(path, orient="split", force_ascii=False)


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print("usage: sandbox_child.py <input.json> <output.json> <code.py> <meta.json>", file=sys.stderr)
        return 2

    input_path, output_path, code_path, meta_path = (Path(arg) for arg in argv[1:])
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    _apply_memory_limit(float(meta.get("memory_limit_gb", 1.0)))

    df = _load_dataframe(input_path)
    code = code_path.read_text(encoding="utf-8")
    _validate_code(code)

    namespace: dict = {
        "pd": pd,
        "np": np,
        "df": df,
        "__builtins__": {
            "len": len,
            "range": range,
            "min": min,
            "max": max,
            "sum": sum,
            "abs": abs,
            "round": round,
            "sorted": sorted,
            "list": list,
            "dict": dict,
            "tuple": tuple,
            "set": set,
            "float": float,
            "int": int,
            "str": str,
            "bool": bool,
            "True": True,
            "False": False,
            "None": None,
            "zip": zip,
            "enumerate": enumerate,
            "map": map,
            "filter": filter,
            "any": any,
            "all": all,
            "isinstance": isinstance,
        },
    }
    exec(compile(code, "<sandbox>", "exec"), namespace, namespace)  # noqa: S102

    result = namespace.get("result")
    if result is None:
        raise ValueError("코드 실행 후 `result` 변수가 설정되지 않았습니다.")
    if not isinstance(result, pd.DataFrame):
        raise ValueError("`result`는 pandas DataFrame이어야 합니다.")

    _save_dataframe(result, output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
