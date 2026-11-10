#!/usr/bin/env bash
# Launch cfrWriter, creating a local virtualenv / installing deps as needed.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

[ -x .venv/bin/python ] || python3 -m venv .venv
if ! .venv/bin/python -c "import PySide6" 2>/dev/null; then
    # Some venvs (e.g. made by uv or an editor) have no pip; bootstrap it.
    .venv/bin/python -m pip --version >/dev/null 2>&1 \
        || .venv/bin/python -m ensurepip --upgrade >/dev/null 2>&1 \
        || { rm -rf .venv && python3 -m venv .venv; }
    .venv/bin/python -m pip install --quiet -r requirements.txt
fi

exec .venv/bin/python main.py "$@"
