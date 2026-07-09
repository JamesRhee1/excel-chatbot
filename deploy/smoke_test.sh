#!/usr/bin/env bash
# Deployment smoke test for excel-chatbot (read-only; no sudo, no restarts).
# Usage: bash deploy/smoke_test.sh
set -uo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OLLAMA_MODEL="${OLLAMA_MODEL:-qwen2.5:7b}"
LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
PASS=0
FAIL=0
RESULTS=()

TRACE_DIR="$(
  systemctl show excel-chatbot -p Environment --value 2>/dev/null \
    | tr ' ' '\n' \
    | sed -n 's/^EXCEL_CHATBOT_TRACE_DIR=//p' \
    | head -1
)"
if [[ -z "${TRACE_DIR}" ]]; then
  TRACE_DIR="${APP_DIR}/traces"
fi

PYTHON="${APP_DIR}/.venv/bin/python"
FIXTURE="${APP_DIR}/evals/fixtures/budget_comparison.xlsx"
E2E_JSON="$(mktemp)"
trap 'rm -f "${E2E_JSON}"' EXIT

RULE_TRACE=""
LLM_TRACE=""

pass() {
  RESULTS+=("[PASS] $1")
  PASS=$((PASS + 1))
  echo "[PASS] $1"
}

fail() {
  RESULTS+=("[FAIL] $1")
  FAIL=$((FAIL + 1))
  echo "[FAIL] $1"
}

info() {
  echo "[INFO] $1"
}

echo "=== excel-chatbot smoke test ==="
echo "APP_DIR=${APP_DIR}"
echo "TRACE_DIR=${TRACE_DIR}"
echo "OLLAMA_MODEL=${OLLAMA_MODEL}"
echo "LAN_IP=${LAN_IP:-"(none)"}"
echo

# --- 1) Service status ---
echo "--- 1) Service status ---"
if [[ "$(systemctl is-active excel-chatbot 2>/dev/null || true)" == "active" ]]; then
  pass "excel-chatbot is active"
else
  fail "excel-chatbot is active (got: $(systemctl is-active excel-chatbot 2>/dev/null || echo unknown))"
fi

if [[ "$(systemctl is-enabled excel-chatbot 2>/dev/null || true)" == "enabled" ]]; then
  pass "excel-chatbot is enabled"
else
  fail "excel-chatbot is enabled (got: $(systemctl is-enabled excel-chatbot 2>/dev/null || echo unknown))"
fi

if [[ "$(systemctl is-active ollama 2>/dev/null || true)" == "active" ]]; then
  pass "ollama is active"
else
  fail "ollama is active (got: $(systemctl is-active ollama 2>/dev/null || echo unknown))"
fi

if [[ "$(systemctl is-active excel-chatbot-trace-cleanup.timer 2>/dev/null || true)" == "active" ]]; then
  pass "excel-chatbot-trace-cleanup.timer is active"
else
  fail "excel-chatbot-trace-cleanup.timer is active (got: $(systemctl is-active excel-chatbot-trace-cleanup.timer 2>/dev/null || echo unknown))"
fi

# --- 2) Network binding ---
echo
echo "--- 2) Network binding ---"
if ss -tln 2>/dev/null | grep -qE '0\.0\.0\.0:8501|[[:space:]]\*:8501'; then
  pass "ss shows 0.0.0.0:8501 (or *:8501)"
else
  fail "ss shows 0.0.0.0:8501 (or *:8501)"
fi

HTTP_LOCAL="$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://127.0.0.1:8501 2>/dev/null || echo "000")"
if [[ "${HTTP_LOCAL}" == "200" ]]; then
  pass "HTTP 127.0.0.1:8501 == 200"
else
  fail "HTTP 127.0.0.1:8501 == 200 (got: ${HTTP_LOCAL})"
fi

if [[ -n "${LAN_IP}" ]]; then
  HTTP_LAN="$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://${LAN_IP}:8501" 2>/dev/null || echo "000")"
  if [[ "${HTTP_LAN}" == "200" ]]; then
    pass "HTTP ${LAN_IP}:8501 == 200"
  else
    fail "HTTP ${LAN_IP}:8501 == 200 (got: ${HTTP_LAN})"
  fi
else
  fail "LAN IP from hostname -I (empty)"
fi

# --- 3) Ollama ---
echo
echo "--- 3) Ollama ---"
TAGS_JSON="$(curl -s --max-time 5 http://127.0.0.1:11434/api/tags 2>/dev/null || true)"
if [[ -n "${TAGS_JSON}" ]] && printf '%s' "${TAGS_JSON}" | grep -q "${OLLAMA_MODEL}"; then
  pass "Ollama /api/tags includes ${OLLAMA_MODEL}"
else
  fail "Ollama /api/tags includes ${OLLAMA_MODEL}"
fi

# --- 4) Functional E2E via executor.run() ---
echo
echo "--- 4) Functional E2E ---"

if [[ ! -x "${PYTHON}" ]]; then
  fail "venv python exists at ${PYTHON}"
elif [[ ! -f "${FIXTURE}" ]]; then
  fail "fixture exists at ${FIXTURE}"
else
  set +e
  EXCEL_CHATBOT_TRACE_DIR="${TRACE_DIR}" \
  OLLAMA_MODEL="${OLLAMA_MODEL}" \
  FIXTURE_PATH="${FIXTURE}" \
  E2E_OUT_PATH="${E2E_JSON}" \
  timeout 120 "${PYTHON}" - <<'PY'
import json
import os
import time
from pathlib import Path

from agent.executor import run

fixture = Path(os.environ["FIXTURE_PATH"])
model = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
out_path = Path(os.environ["E2E_OUT_PATH"])


def summarize(label, result, elapsed_ms):
    df = result.get("raw_df")
    if df is None:
        df = result.get("df")
    rows = len(df) if df is not None else 0
    return {
        "label": label,
        "success": bool(result.get("success")),
        "route_path": result.get("route_path"),
        "rows": rows,
        "trace_id": result.get("trace_id"),
        "elapsed_ms": round(elapsed_ms, 1),
        "error": result.get("error"),
    }


t0 = time.perf_counter()
rule = run(
    file_path=str(fixture),
    user_message="당년도예산 0보다 큰 항목 보여줘",
    model=model,
)
rule_ms = (time.perf_counter() - t0) * 1000

t1 = time.perf_counter()
llm = run(
    file_path=str(fixture),
    user_message="집행이 저조한 항목 위주로 정리해줘",
    model=model,
)
llm_ms = (time.perf_counter() - t1) * 1000

payload = {
    "rule": summarize("rule", rule, rule_ms),
    "llm": summarize("llm", llm, llm_ms),
}
out_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
print(json.dumps(payload, ensure_ascii=False, indent=2))
PY
  E2E_RC=$?

  if [[ ${E2E_RC} -ne 0 || ! -s "${E2E_JSON}" ]]; then
    fail "E2E python run completed (exit=${E2E_RC})"
  else
    RULE_SUCCESS="$("${PYTHON}" -c 'import json; d=json.load(open("'"${E2E_JSON}"'")); print(d["rule"]["success"])')"
    RULE_ROUTE="$("${PYTHON}" -c 'import json; d=json.load(open("'"${E2E_JSON}"'")); print(d["rule"]["route_path"])')"
    RULE_ROWS="$("${PYTHON}" -c 'import json; d=json.load(open("'"${E2E_JSON}"'")); print(d["rule"]["rows"])')"
    RULE_TRACE="$("${PYTHON}" -c 'import json; d=json.load(open("'"${E2E_JSON}"'")); print(d["rule"]["trace_id"] or "")')"
    RULE_MS="$("${PYTHON}" -c 'import json; d=json.load(open("'"${E2E_JSON}"'")); print(d["rule"]["elapsed_ms"])')"
    RULE_ERR="$("${PYTHON}" -c 'import json; d=json.load(open("'"${E2E_JSON}"'")); print(d["rule"].get("error") or "")')"

    LLM_SUCCESS="$("${PYTHON}" -c 'import json; d=json.load(open("'"${E2E_JSON}"'")); print(d["llm"]["success"])')"
    LLM_ROUTE="$("${PYTHON}" -c 'import json; d=json.load(open("'"${E2E_JSON}"'")); print(d["llm"]["route_path"])')"
    LLM_ROWS="$("${PYTHON}" -c 'import json; d=json.load(open("'"${E2E_JSON}"'")); print(d["llm"]["rows"])')"
    LLM_TRACE="$("${PYTHON}" -c 'import json; d=json.load(open("'"${E2E_JSON}"'")); print(d["llm"]["trace_id"] or "")')"
    LLM_MS="$("${PYTHON}" -c 'import json; d=json.load(open("'"${E2E_JSON}"'")); print(d["llm"]["elapsed_ms"])')"
    LLM_ERR="$("${PYTHON}" -c 'import json; d=json.load(open("'"${E2E_JSON}"'")); print(d["llm"].get("error") or "")')"

    info "rule: success=${RULE_SUCCESS} route=${RULE_ROUTE} rows=${RULE_ROWS} trace_id=${RULE_TRACE} total_ms=${RULE_MS}"
    if [[ "${RULE_SUCCESS}" == "True" && "${RULE_ROUTE}" == "rule" && "${RULE_ROWS}" -gt 0 ]]; then
      pass "E2E rule query (당년도예산 0보다 큰 항목 보여줘)"
    else
      fail "E2E rule query (success+rule+rows>0; err=${RULE_ERR})"
    fi

    info "llm: success=${LLM_SUCCESS} route=${LLM_ROUTE} rows=${LLM_ROWS} trace_id=${LLM_TRACE} total_ms=${LLM_MS}"
    if [[ "${LLM_SUCCESS}" == "True" && "${LLM_ROUTE}" == "llm" ]]; then
      pass "E2E LLM query (집행이 저조한 항목 위주로 정리해줘) ${LLM_MS}ms"
    else
      fail "E2E LLM query (success+llm route; route=${LLM_ROUTE} err=${LLM_ERR}) ${LLM_MS}ms"
    fi
  fi
fi

# --- 5) Trace recording ---
echo
echo "--- 5) Trace recording ---"
TODAY="$(date -u +%Y%m%d)"
TRACE_FILE="${TRACE_DIR}/traces_${TODAY}.jsonl"

if [[ -f "${TRACE_FILE}" ]]; then
  LAST_TRACE_ID="$(tail -n 1 "${TRACE_FILE}" | "${PYTHON}" -c 'import json,sys; print(json.loads(sys.stdin.read()).get("trace_id",""))' 2>/dev/null || true)"
  info "last line of ${TRACE_FILE}: trace_id=${LAST_TRACE_ID}"
  if [[ -n "${LLM_TRACE}" && "${LAST_TRACE_ID}" == "${LLM_TRACE}" ]]; then
    pass "today's traces_*.jsonl last line matches LLM trace_id"
  else
    fail "today's traces_*.jsonl last line matches LLM trace_id (last=${LAST_TRACE_ID} expected=${LLM_TRACE})"
  fi
else
  fail "today's trace file exists (${TRACE_FILE})"
fi

# --- 6) Resources (informational) ---
echo
echo "--- 6) Resources ---"
if command -v free >/dev/null 2>&1; then
  AVAIL_MB="$(free -m | awk 'NR==2 {print $NF}')"
  info "available memory: ${AVAIL_MB} MiB"
else
  info "free not available"
fi
if command -v nvidia-smi >/dev/null 2>&1; then
  info "GPU: $(nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader 2>/dev/null | head -1)"
else
  info "nvidia-smi not present"
fi

# --- Summary ---
echo
echo "=== Summary: ${PASS} PASS / ${FAIL} FAIL ==="
for line in "${RESULTS[@]}"; do
  echo "${line}"
done

if [[ "${FAIL}" -eq 0 ]]; then
  exit 0
fi
exit 1
