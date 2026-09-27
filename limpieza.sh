#!/usr/bin/env bash
# Made by Sinfallas <sinfallas@yahoo.com>
# Licence: GPL-2
LC_ALL=C

if [[ "$EUID" != "0" ]]; then
        echo "ERROR: debe ser root."
        exit 1
fi

clear
rm -f .coverage
rm -f .mutmut-cache
rm -rf .mypy_cache
rm -rf .pytest_cache
rm -rf .ruff_cache
rm -rf .tox
rm -rf .hypothesis
rm -rf .schemathesis
rm -rf dist
rm -rf build
rm -rf tests/__pycache__
rm -rf __pycache__
rm -rf .buildx-cache
rm -rf mutants
rm -rf *.egg-info
docker system prune -af
docker volume prune -af
echo "Finalizado."
exit 0
