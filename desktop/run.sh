#!/usr/bin/env bash
# Launch Beat Studio. Double-clickable (mark executable) or run: bash run.sh
cd "$(dirname "$0")" || exit 1
exec ./.venv/bin/python app.py "$@"
