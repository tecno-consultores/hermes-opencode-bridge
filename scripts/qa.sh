#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
# Fases de QA dentro del contenedor efímero (docker-compose.qa.yml). Uso:
#   docker compose -f docker-compose.qa.yml run --rm test ./scripts/qa.sh <fase>
# Fases: tox | lint | unit | sast | mutation | load | fuzz | all
set -euo pipefail

cd "$(dirname "$0")/.."
export COVERAGE_FILE=/tmp/.coverage MYPY_CACHE_DIR=/tmp/.mypy_cache RUFF_CACHE_DIR=/tmp/.ruff_cache
API_URL="${API_URL:-http://api:8000}"

venv() {
    # Idempotente: reutiliza el venv efímero si ya existe y solo instala lo que falte.
    uv venv -q --allow-existing /tmp/venv
    VIRTUAL_ENV=/tmp/venv uv pip install -q -e ".[dev]"
    # shellcheck disable=SC1091
    source /tmp/venv/bin/activate
}

fase_lint() {
    venv
    ruff check acp_api.py tests/ locustfile.py scripts/
    ruff format --check acp_api.py tests/ locustfile.py scripts/
    mypy acp_api.py scripts/mutation_parallel.py
}

fase_unit() {
    venv
    pytest -p no:cacheprovider --cov --cov-report=term-missing
}

fase_sast() {
    venv
    bandit -q -r acp_api.py
    pip-audit --skip-editable
}

fase_mutation() {
    venv
    # Varios procesos mutmut independientes (shards) en paralelo; ver scripts/mutation_parallel.py
    python scripts/mutation_parallel.py
}

fase_load() {
    venv
    locust -f locustfile.py --headless -u 100 -r 10 -t 1m --host "$API_URL"
}

fase_fuzz() {
    venv
    schemathesis run "$API_URL/openapi.json" --exclude-checks positive_data_acceptance
}

fase_tox() {
    uvx --with tox-uv tox
}

case "${1:-tox}" in
    tox) fase_tox ;;
    lint) fase_lint ;;
    unit) fase_unit ;;
    sast) fase_sast ;;
    mutation) fase_mutation ;;
    load) fase_load ;;
    fuzz) fase_fuzz ;;
    all) fase_lint && fase_unit && fase_sast ;;
    *) echo "Fase desconocida: $1 (tox|lint|unit|sast|mutation|load|fuzz|all)" >&2; exit 2 ;;
esac
