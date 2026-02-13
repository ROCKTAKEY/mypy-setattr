#!/usr/bin/env bash
set -euo pipefail

uv run pytest -n auto "$@" --cov
uv run coverage report
uv run coverage json
