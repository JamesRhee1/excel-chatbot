#!/usr/bin/env bash
# Idempotent installer for excel-chatbot systemd units (LAN / Tailscale private network).
# Example:
#   ./deploy/install.sh --bind 0.0.0.0
# Trusted LAN assumed. Do not expose publicly; bind to a Tailscale IP when needed.
set -euo pipefail

APP_USER="$(id -un)"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIND_ADDR="0.0.0.0"

usage() {
  cat <<'USAGE'
Usage: ./deploy/install.sh [--user USER] [--dir DIR] [--bind ADDR]

  --user   systemd service user (default: current user)
  --dir    application directory (default: repository root)
  --bind   Streamlit --server.address (default: 0.0.0.0)
           Trusted LAN assumed. Do not expose publicly;
           use a Tailscale IP (e.g. 100.x.y.z) to limit access when needed.

This script only writes under /etc/systemd/system/ and calls systemctl.
It does not install Tailscale or Ollama.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user)
      APP_USER="${2:?--user requires a value}"
      shift 2
      ;;
    --dir)
      APP_DIR="$(cd "${2:?--dir requires a value}" && pwd)"
      shift 2
      ;;
    --bind)
      BIND_ADDR="${2:?--bind requires a value}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT_SRC="${SCRIPT_DIR}/excel-chatbot.service"
CLEANUP_SERVICE_SRC="${SCRIPT_DIR}/excel-chatbot-trace-cleanup.service"
CLEANUP_TIMER_SRC="${SCRIPT_DIR}/excel-chatbot-trace-cleanup.timer"

for required in "${UNIT_SRC}" "${CLEANUP_SERVICE_SRC}" "${CLEANUP_TIMER_SRC}"; do
  if [[ ! -f "${required}" ]]; then
    echo "Missing deploy asset: ${required}" >&2
    exit 1
  fi
done

if [[ ! -d "${APP_DIR}" ]]; then
  echo "Application directory not found: ${APP_DIR}" >&2
  exit 1
fi

if [[ ! -x "${APP_DIR}/.venv/bin/streamlit" ]]; then
  echo "Creating virtualenv and installing package in ${APP_DIR} ..."
  python3 -m venv "${APP_DIR}/.venv"
  # shellcheck disable=SC1091
  source "${APP_DIR}/.venv/bin/activate"
  pip install -U pip
  pip install -e "${APP_DIR}"
else
  echo "Existing venv found at ${APP_DIR}/.venv — skipping pip install."
fi

mkdir -p "${APP_DIR}/traces"

render_unit() {
  local src="$1"
  local dest="$2"
  sed \
    -e "s|%APP_USER%|${APP_USER}|g" \
    -e "s|%APP_DIR%|${APP_DIR}|g" \
    -e "s|%BIND_ADDR%|${BIND_ADDR}|g" \
    "${src}" > "${dest}"
}

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

render_unit "${UNIT_SRC}" "${TMP_DIR}/excel-chatbot.service"
render_unit "${CLEANUP_SERVICE_SRC}" "${TMP_DIR}/excel-chatbot-trace-cleanup.service"
cp "${CLEANUP_TIMER_SRC}" "${TMP_DIR}/excel-chatbot-trace-cleanup.timer"

echo "Installing systemd units (sudo may prompt for password) ..."
sudo cp "${TMP_DIR}/excel-chatbot.service" /etc/systemd/system/excel-chatbot.service
sudo cp "${TMP_DIR}/excel-chatbot-trace-cleanup.service" /etc/systemd/system/excel-chatbot-trace-cleanup.service
sudo cp "${TMP_DIR}/excel-chatbot-trace-cleanup.timer" /etc/systemd/system/excel-chatbot-trace-cleanup.timer

sudo systemctl daemon-reload
sudo systemctl enable --now excel-chatbot.service
sudo systemctl enable --now excel-chatbot-trace-cleanup.timer

echo
echo "excel-chatbot active: $(systemctl is-active excel-chatbot.service || true)"
echo "trace cleanup timer: $(systemctl is-active excel-chatbot-trace-cleanup.timer || true)"
echo "Open: http://${BIND_ADDR}:8501"
echo "Logs: journalctl -u excel-chatbot -f"
