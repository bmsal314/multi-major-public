#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
PYTHON_BIN="${PYTHON_BIN:-python3}"
"$PYTHON_BIN" -c 'import sys; assert (3,11)<=sys.version_info[:2]<(3,13), "Use Python 3.11 or 3.12"'
node -e 'if(Number(process.versions.node.split(".")[0])!==24)throw Error("Use Node 24")'
if [ ! -x backend/.venv/bin/python ]; then "$PYTHON_BIN" -m venv backend/.venv; fi
backend/.venv/bin/python -m pip install -r backend/requirements-dev.txt
npm --prefix frontend ci
backend/.venv/bin/python -m scripts.generate_contracts --check
printf '\nDependencies ready. Configure .env using .env.example, then run make dev.\nNo cloud resources were created and no student data was migrated.\n'
