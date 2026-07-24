#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON:-python3}"

echo "[devx-quickcheck] starting"
"${PYTHON_BIN}" -m aigit.cli chunk --repo .

if command -v aigit >/dev/null 2>&1; then
  AIGIT_BIN="aigit"
else
  AIGIT_BIN="${PYTHON_BIN} -m aigit.cli"
fi

echo "[devx-quickcheck] refreshing semantic state"
${AIGIT_BIN} chunk --repo .

if ${AIGIT_BIN} improve --repo . "${1:-}" ; then
  echo "[devx-quickcheck] aigit improve passed"
  exit 0
fi

echo "[devx-quickcheck] fallback checks because improve failed or environment is partial"
if command -v ruff >/dev/null 2>&1; then
  echo "[devx-quickcheck] running ruff check"
  ruff check .
else
  echo "[devx-quickcheck] ruff not found, skipping lint"
fi

if "${PYTHON_BIN}" - <<'PY'
import importlib.util
raise SystemExit(0 if importlib.util.find_spec("pytest") else 1)
PY
then
  echo "[devx-quickcheck] running pytest"
  "${PYTHON_BIN}" -m pytest --tb=short -q "${1:-tests}"
else
  echo "[devx-quickcheck] pytest missing, skipping tests"
fi

echo "[devx-quickcheck] complete"
