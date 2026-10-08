#!/usr/bin/env sh
# Run lint + tests under CPython 3.11 AND 3.13 (uv downloads missing interpreters).
set -eu
cd "$(dirname "$0")/.."
for v in 3.11 3.13; do
  venv=".venv$(echo "$v" | tr -d .)"
  echo "=== Python $v ($venv) ==="
  [ -d "$venv" ] || uv venv "$venv" --python "$v" -q
  if [ -x "$venv/bin/python" ]; then py="$venv/bin/python"; else py="$venv/Scripts/python.exe"; fi
  uv pip install -q --python "$py" -e ".[dev,ml,agent]"
  "$py" -m compileall -q src tests
  "$py" -m pytest
done
uv tool run ruff check src tests
echo "OK: 3.11 and 3.13 both green"
