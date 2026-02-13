#!/usr/bin/env bash
set -euo pipefail

uv run mypy .
uv run basedpyright
uv run ty check --error-on-warning
