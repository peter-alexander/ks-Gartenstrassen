#!/usr/bin/env bash
# Backward-compatible entrypoint. The old data/wien/ structure is retired.
set -euo pipefail
cd "$(dirname "$0")/.."
exec "${PYTHON:-.venv/bin/python}" -m scripts.consolidate_wien_data "$@"
