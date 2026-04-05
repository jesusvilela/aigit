#!/usr/bin/env bash
set -euo pipefail

echo "[devx-quickcheck] starting"
python -m aigit.cli chunk --repo .

if command -v ruff >/dev/null 2>&1; then
  echo "[devx-quickcheck] running ruff check"
  ruff check .
else
  echo "[devx-quickcheck] ruff not found, skipping lint"
fi

if python - <<'PY'
import importlib.util
raise SystemExit(0 if importlib.util.find_spec("pytest") else 1)
PY
then
  echo "[devx-quickcheck] running pytest"
  python -m pytest --tb=short -q "${1:-tests}"
else
  echo "[devx-quickcheck] pytest missing, skipping tests"
fi

echo "[devx-quickcheck] complete"
