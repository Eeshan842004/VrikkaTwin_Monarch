#!/usr/bin/env bash
# Thin wrapper (master plan §18 names this script). The real logic, including licence printing and the
# refusal of credentialed datasets, lives in download_public_data.py so it also runs on Windows.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-.venv/bin/python}"
[ -x "$PY" ] || PY=python
exec "$PY" scripts/download_public_data.py "$@"
