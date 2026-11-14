#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Pruebas de mutación en paralelo con puerta de calidad (MSI mínimo).

``mutmut`` ya lanza un proceso hijo (``fork``) por mutante, pero con el valor por
defecto (un hijo por CPU) los hijos pasan la mayor parte del tiempo esperando la
E/S simulada de las pruebas asíncronas. Este script:

- sobresuscribe la CPU (``2 x nproc`` hijos por defecto);
- opcionalmente reparte las funciones de ``acp_api.py`` en varios procesos
  ``mutmut`` independientes (*shards*), cada uno en una copia aislada del repositorio,
  para máquinas grandes donde el orquestador único de mutmut sea el cuello de botella;
- agrega los resultados, lista los sobrevivientes y falla si el MSI es menor al mínimo.

Variables de entorno:

- ``MUTATION_SHARDS``: procesos mutmut independientes (por defecto 1).
- ``MUTATION_CHILDREN``: hijos por shard (por defecto ``2 * nproc // shards``).
- ``MUTATION_MIN_MSI``: MSI mínimo exigido en % (por defecto 80).
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = "acp_api.py"
MODULE = "acp_api"
COPY_IGNORE = shutil.ignore_patterns(
    "mutants", ".tox", ".git", "graphify-out", "opencode-workspace", "__pycache__", "*.egg-info", ".*_cache"
)
PROGRESS = re.compile(r"🎉 (\d+) 🫥 (\d+)\s+⏰ (\d+)\s+🤔 (\d+)\s+🙁 (\d+)\s+🔇 (\d+)")
RESULT_LINE = re.compile(r"^\s*(\S+__mutmut_\d+): (.+)$")


@dataclass
class Shard:
    index: int
    patterns: list[str] = field(default_factory=list)
    weight: int = 0


@dataclass
class Totals:
    killed: int = 0
    no_tests: int = 0
    timeout: int = 0
    suspicious: int = 0
    survived: int = 0
    skipped: int = 0
    pending: list[str] = field(default_factory=list)

    def add(self, counts: tuple[int, ...]) -> None:
        self.killed += counts[0]
        self.no_tests += counts[1]
        self.timeout += counts[2]
        self.suspicious += counts[3]
        self.survived += counts[4]
        self.skipped += counts[5]

    @property
    def total(self) -> int:
        return self.killed + self.no_tests + self.timeout + self.suspicious + self.survived

    @property
    def msi(self) -> float:
        # Los timeouts cuentan como detectados (convención de Stryker); "sin tests" como no detectados.
        return 100.0 * (self.killed + self.timeout) / self.total if self.total else 0.0


def mutable_functions(source: Path) -> list[tuple[str, int]]:
    """Patrones mutmut (``x_func`` / ``xǁClaseǁmétodo``) con su tamaño en líneas."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    found: list[tuple[str, int]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.append((f"{MODULE}.x_{node.name}__mutmut_*", _size(node)))
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    found.append((f"{MODULE}.xǁ{node.name}ǁ{item.name}__mutmut_*", _size(item)))
    return found


def _size(node: ast.AST) -> int:
    return (getattr(node, "end_lineno", 0) or 0) - (getattr(node, "lineno", 0) or 0) + 1


def balance(functions: list[tuple[str, int]], shards: int) -> list[Shard]:
    """Reparto voraz por tamaño (LPT) para equilibrar la carga entre shards."""
    buckets = [Shard(i) for i in range(shards)]
    for pattern, weight in sorted(functions, key=lambda f: f[1], reverse=True):
        target = min(buckets, key=lambda b: b.weight)
        target.patterns.append(pattern)
        target.weight += weight
    return [b for b in buckets if b.patterns]


def launch(shard: Shard, workdir: Path, children: int) -> subprocess.Popen[str]:
    shutil.copytree(ROOT, workdir, ignore=COPY_IGNORE)
    env = {**os.environ, "COVERAGE_FILE": str(workdir / ".coverage"), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.Popen(  # noqa: S603 - comando fijo, sin shell
        ["mutmut", "run", "--max-children", str(children), *shard.patterns],  # noqa: S607
        cwd=workdir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def collect(shard: Shard, workdir: Path, output: str, totals: Totals) -> bool:
    matches = PROGRESS.findall(output.replace("\r", "\n"))
    if not matches:
        print(f"[shard {shard.index}] sin resultados de mutmut:\n{output[-2000:]}", file=sys.stderr)
        return False
    totals.add(tuple(int(n) for n in matches[-1]))
    results = subprocess.run(
        ["mutmut", "results"],  # noqa: S607
        cwd=workdir,
        capture_output=True,
        text=True,
        check=False,
    )
    for line in results.stdout.splitlines():
        match = RESULT_LINE.match(line)
        # Cada shard ve los mutantes de los demás como "not checked": se ignoran.
        if match and match.group(2).strip() != "not checked":
            totals.pending.append(f"{match.group(1)}: {match.group(2)}")
    return True


def main() -> int:
    cpus = os.cpu_count() or 4
    # Un valor vacío (p. ej. interpolado por docker compose) equivale a "no definido".
    shards_wanted = max(1, int(os.environ.get("MUTATION_SHARDS") or 1))
    children = int(os.environ.get("MUTATION_CHILDREN") or max(2, (2 * cpus) // shards_wanted))
    min_msi = float(os.environ.get("MUTATION_MIN_MSI") or 80)

    shards = balance(mutable_functions(ROOT / SOURCE), shards_wanted)
    print(f"Mutación paralela: {len(shards)} shards x {children} hijos ({cpus} CPU)")
    start = time.monotonic()
    base = Path(tempfile.mkdtemp(prefix="mutmut-shards-"))
    try:
        procs = [(s, base / f"shard-{s.index}") for s in shards]
        running = [(s, wd, launch(s, wd, children)) for s, wd in procs]
        totals = Totals()
        ok = True
        for shard, workdir, proc in running:
            output, _ = proc.communicate()
            ok = collect(shard, workdir, output, totals) and ok
    finally:
        shutil.rmtree(base, ignore_errors=True)

    elapsed = time.monotonic() - start
    print(
        f"\nTotal {totals.total} mutantes en {elapsed:.0f}s | 🎉 muertos {totals.killed} | ⏰ timeout {totals.timeout}"
        f" | 🙁 sobrevivientes {totals.survived} | 🫥 sin tests {totals.no_tests}"
        f" | 🤔 sospechosos {totals.suspicious} | 🔇 omitidos {totals.skipped}"
    )
    for line in sorted(totals.pending):
        print(f"    {line}")
    print(f"MSI: {totals.msi:.1f} % (mínimo {min_msi:.0f} %)")
    return 0 if ok and totals.msi >= min_msi else 1


if __name__ == "__main__":
    sys.exit(main())
