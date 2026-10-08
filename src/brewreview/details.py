"""Slow per-formula details, gathered in the background while you answer prompts.

Disk usage means walking each keg in the Cellar, which takes a moment for large
formulae. Rather than making you wait up front, a thread pool starts on all of
them right away, in review order, so the details for the formula on screen are
usually ready by the time it's shown.
"""

from __future__ import annotations

import os
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from brewreview.brew import Formula, Inventory


def disk_usage(path: Path) -> int:
    """Bytes allocated on disk under `path` (like ``du``), 0 if it's missing."""
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_blocks * 512
            except OSError:
                pass
    return total


def last_used(opt_dir: Path) -> datetime | None:
    """Most recent access time of the formula's executables, if it has any.

    macOS updates a file's access time when it's run (at most about once a day,
    and only if it hasn't been read since it was last modified), so this is a
    reasonable "when did I last run this" signal for command-line tools. It
    says nothing about libraries, which are never run directly.
    """
    times = []
    for sub in ("bin", "sbin"):
        directory = opt_dir / sub
        if not directory.is_dir():
            continue
        for entry in directory.iterdir():
            try:
                times.append(entry.stat().st_atime)  # follows the symlink
            except OSError:
                pass
    return datetime.fromtimestamp(max(times), UTC) if times else None


class DetailsLoader:
    """Computes sizes and last-used times on a background thread pool."""

    def __init__(self, inventory: Inventory, order: list[Formula]):
        self._inventory = inventory
        self._pool = ThreadPoolExecutor(max_workers=4)
        self._sizes: dict[str, Future[int]] = {}
        self._used: dict[str, Future[datetime | None]] = {}
        # Candidates first, in the order they'll be shown; then everything else,
        # since any formula may turn up as a dependency freed by a removal.
        for f in order:
            self._used[f.name] = self._pool.submit(
                last_used, inventory.prefix / "opt" / f.short_name
            )
            self._submit_size(f)
        for f in inventory.formulae.values():
            self._submit_size(f)

    def _submit_size(self, f: Formula) -> None:
        if f.name not in self._sizes:
            self._sizes[f.name] = self._pool.submit(
                disk_usage, self._inventory.cellar / f.short_name
            )

    def size(self, name: str) -> int:
        """Disk usage of a formula's keg; waits if it's still being computed."""
        return self._sizes[name].result()

    def last_used(self, name: str) -> datetime | None:
        """Last time one of the formula's executables ran; may wait."""
        return self._used[name].result()

    def close(self) -> None:
        """Stop pending work so the program can exit promptly."""
        self._pool.shutdown(wait=False, cancel_futures=True)
