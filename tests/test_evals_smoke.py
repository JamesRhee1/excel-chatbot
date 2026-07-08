"""Smoke test for eval harness (--no-llm rule-path queries)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_run_evals_no_llm_rule_paths_pass() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    cmd = [sys.executable, str(repo_root / "evals" / "run_evals.py"), "--no-llm"]
    completed = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr
