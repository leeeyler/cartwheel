#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if curl --silent --fail http://127.0.0.1:8011/api/status >/dev/null 2>&1; then
  exit 0
fi
mkdir -p .workbench
nohup python -m uv run python -m server.workbench --host 0.0.0.0 >.workbench/server.log 2>&1 &
