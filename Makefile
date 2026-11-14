# SPDX-License-Identifier: GPL-2.0-only
# Atajos de QA: todo se ejecuta en contenedores efímeros sin root (docker-compose.qa.yml).
QA := HOST_UID=$$(id -u) HOST_GID=$$(id -g) docker compose -f docker-compose.qa.yml
RUN := $(QA) run --rm test ./scripts/qa.sh

.PHONY: lint unit sast mutation tox load fuzz all ci clean

lint:      ## ruff + mypy --strict
	$(RUN) lint
unit:      ## pytest con cobertura >= 95 %
	$(RUN) unit
sast:      ## bandit + pip-audit
	$(RUN) sast
mutation:  ## mutmut en paralelo (MSI >= 80 %)
	$(RUN) mutation
tox:       ## matriz Python 3.10-3.14
	$(RUN) tox
load:      ## locust contra la API de QA
	$(QA) up -d --wait api && $(RUN) load
fuzz:      ## schemathesis contra la API de QA
	$(QA) up -d --wait api && $(RUN) fuzz
all:       ## lint + unit + sast
	$(RUN) all
ci: tox sast mutation
clean:     ## artefactos locales y contenedores de QA
	./limpieza.sh
