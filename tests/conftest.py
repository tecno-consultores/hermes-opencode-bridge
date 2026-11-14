# SPDX-License-Identifier: GPL-2.0-only
"""Fixtures globales de la suite."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

import acp_api


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Aísla cada prueba de las variables del host y del estado global."""
    for name in (
        "HERMES_API_URL",
        "HERMES_API_KEY",
        "HERMES_SECURITY_PROMPT",
        "HERMES_MODEL",
        "HERMES_TIMEOUT",
        "OPENCODE_CONTAINER",
        "OPENCODE_WORKSPACE",
        "OPENCODE_TASK_TIMEOUT",
        "MAX_FEEDBACK_ROUNDS",
        "MAX_CONCURRENT_TASKS",
        "MCP_ALLOWED_HOSTS",
        "ACP_ENABLE_DOCS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ACP_API_KEY", "token-de-prueba-0123456789abcdef")
    acp_api._task_semaphore = None
    yield
    acp_api._task_semaphore = None
