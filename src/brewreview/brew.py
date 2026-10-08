"""Querying Homebrew for the installed formulae and their relationships.

Everything here comes from two fast `brew` calls that run in parallel:

- ``brew info --json=v2 --installed`` returns metadata for *every* installed
  formula in one go (well under a second), which is far quicker than calling
  ``brew info <name>`` once per formula.
- ``brew leaves`` lists the formulae nothing else depends on. Only these can be
  uninstalled without breaking another formula, so they are the review
  candidates.

A leaf is one of two kinds, distinguished by ``installed_on_request`` in the
JSON (this is exactly what ``brew leaves -r`` / ``brew leaves -p`` filter on):

- *requested*: you ran ``brew install <name>`` yourself.
- *orphaned*: it was pulled in as a dependency, but whatever needed it has
  since been removed.
"""

from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


class BrewError(RuntimeError):
    """A `brew` command failed."""


def run_brew(*args: str) -> str:
    """Run ``brew <args>`` and return its stdout, raising BrewError on failure."""
    try:
        result = subprocess.run(
            ["brew", *args], capture_output=True, text=True, check=True
        )
    except FileNotFoundError as e:
        raise BrewError("`brew` not found on PATH") from e
    except subprocess.CalledProcessError as e:
        raise BrewError(f"`brew {' '.join(args)}` failed: {e.stderr.strip()}") from e
    return result.stdout


@dataclass
class Formula:
    """The parts of an installed formula that matter for the review."""

    name: str  # full name, e.g. "git" or "infogrind/tap/ccmove"
    short_name: str  # name of the keg directory in the Cellar
    desc: str
    homepage: str
    version: str
    installed_at: datetime | None
    on_request: bool
    deprecated: str | None = None  # reason, or "" if no reason given
    disabled: str | None = None
    runtime_deps: list[str] = field(default_factory=list)


@dataclass
class Inventory:
    """All installed formulae plus the subset that are leaves."""

    formulae: dict[str, Formula]
    leaves: list[str]
    cellar: Path
    prefix: Path

    def candidates(self) -> list[Formula]:
        """Leaves in review order: requested ones first, then orphans."""
        leaves = [self.formulae[n] for n in self.leaves if n in self.formulae]
        return sorted(leaves, key=lambda f: (not f.on_request, f.name))

    def dependents(self, name: str) -> set[str]:
        """Installed formulae that need `name` at runtime (directly or not)."""
        return {f.name for f in self.formulae.values() if name in f.runtime_deps}

    def freed_by(self, removing: set[str]) -> set[str]:
        """Dependencies that become orphaned once `removing` is uninstalled.

        These are what ``brew autoremove`` would clean up afterwards. A
        dependency is freed when it wasn't installed on request and everything
        depending on it is also going away. This is an estimate: Homebrew's own
        rules have extra cases (e.g. build dependencies, casks).
        """
        gone = set(removing)
        changed = True
        while changed:
            changed = False
            for name in {d for g in gone for d in self.formulae[g].runtime_deps}:
                dep = self.formulae.get(name)
                if dep is None or dep.on_request or name in gone:
                    continue
                if self.dependents(name) <= gone:
                    gone.add(name)
                    changed = True
        return gone - removing


def parse_formula(data: dict) -> Formula:
    """Build a Formula from one entry of ``brew info --json=v2``."""
    installed = data.get("installed") or [{}]
    # The linked keg is the one in use; otherwise the newest installed version.
    current = next(
        (i for i in installed if i.get("version") == data.get("linked_keg")),
        installed[-1],
    )
    timestamp = current.get("time")
    return Formula(
        name=data["full_name"],
        short_name=data["name"],
        desc=data.get("desc") or "",
        homepage=data.get("homepage") or "",
        version=current.get("version") or "?",
        installed_at=datetime.fromtimestamp(timestamp, UTC).astimezone()
        if timestamp
        else None,
        on_request=bool(current.get("installed_on_request")),
        deprecated=(data.get("deprecation_reason") or "")
        if data.get("deprecated")
        else None,
        disabled=(data.get("disable_reason") or "") if data.get("disabled") else None,
        runtime_deps=[
            d["full_name"] for d in current.get("runtime_dependencies") or []
        ],
    )


def load_inventory() -> Inventory:
    """Ask Homebrew for everything we need, running the calls in parallel."""
    with ThreadPoolExecutor() as pool:
        info = pool.submit(run_brew, "info", "--json=v2", "--installed")
        leaves = pool.submit(run_brew, "leaves")
        cellar = pool.submit(run_brew, "--cellar")
        prefix = pool.submit(run_brew, "--prefix")
    formulae = [parse_formula(f) for f in json.loads(info.result())["formulae"]]
    return Inventory(
        formulae={f.name: f for f in formulae},
        leaves=leaves.result().split(),
        cellar=Path(cellar.result().strip()),
        prefix=Path(prefix.result().strip()),
    )
