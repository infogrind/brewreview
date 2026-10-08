"""Interactive review of installed Homebrew formulae.

Walks through every leaf formula (see brew.py), shows what it is and how much
it's used, and lets you mark it for removal. Nothing is uninstalled until the
end, when you get a summary and a final confirmation.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from importlib.metadata import version

from brewreview.brew import BrewError, Formula, Inventory, load_inventory
from brewreview.details import DetailsLoader

HELP = """\
  y  mark for removal
  n  keep (default, also Enter)
  b  go back to the previous formula
  i  show full `brew info`
  q  stop reviewing and go to the summary
  ?  show this help"""

Ask = Callable[[str], str]


# --- Formatting --------------------------------------------------------------


def _color(code: str) -> Callable[[str], str]:
    def apply(text: str) -> str:
        if sys.stdout.isatty() and "NO_COLOR" not in os.environ:
            return f"\033[{code}m{text}\033[0m"
        return text

    return apply


bold, dim, yellow, red = _color("1"), _color("2"), _color("33"), _color("31")


def format_size(n: int) -> str:
    """Human-readable size, e.g. 1536 -> '1.5 KB'."""
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    raise AssertionError("unreachable")


def format_ago(then: datetime | None, now: datetime | None = None) -> str:
    """Coarse relative time, e.g. '3 days ago', or 'unknown'."""
    if then is None:
        return "unknown"
    days = ((now or datetime.now(UTC)) - then).days
    if days < 1:
        return "today"
    for length, unit in ((365, "year"), (30, "month"), (7, "week"), (1, "day")):
        if days >= length:
            return f"{plural(days // length, unit)} ago"
    raise AssertionError("unreachable")


def plural(count: int, word: str, plural_form: str | None = None) -> str:
    """'1 day', '2 days'; pass `plural_form` for irregular words."""
    return f"{count} {word if count == 1 else plural_form or word + 's'}"


# --- Review loop -------------------------------------------------------------


def show(
    f: Formula,
    position: str,
    inventory: Inventory,
    details: DetailsLoader,
    others: set[str],
    marked: bool,
) -> None:
    """Print everything we know about `f`.

    `others` are the formulae already marked for removal; they're taken into
    account when estimating which dependencies removing `f` would free.
    """
    kind = "installed on request" if f.on_request else "orphaned dependency"
    print(f"{dim(position)} {bold(f.name)} {f.version}  {dim(f'({kind})')}")
    if f.desc:
        print(f"  {f.desc}")
    if f.homepage:
        print(f"  {dim(f.homepage)}")
    if f.disabled is not None:
        print(f"  {red('Disabled upstream')}{': ' + f.disabled if f.disabled else ''}")
    elif f.deprecated is not None:
        print(
            f"  {yellow('Deprecated upstream')}"
            f"{': ' + f.deprecated if f.deprecated else ''}"
        )
    installed = f.installed_at.date().isoformat() if f.installed_at else "?"
    used = details.last_used(f.name)
    used_text = format_ago(used) if used else "n/a (no executables)"
    print(
        f"  Installed {installed} ({format_ago(f.installed_at)})"
        f" · {format_size(details.size(f.name))}"
        f" · last run: {used_text}"
    )
    freed = inventory.freed_by(others | {f.name}) - inventory.freed_by(others)
    if freed:
        size = sum(details.size(n) for n in freed)
        names = ", ".join(sorted(freed))
        print(
            f"  Removing it also frees "
            f"{plural(len(freed), 'dependency', 'dependencies')} "
            f"({format_size(size)}): {names}"
        )
    if marked:
        print(f"  {yellow('Currently marked for removal')}")


def review(
    candidates: list[Formula],
    inventory: Inventory,
    details: DetailsLoader,
    ask: Ask = input,
) -> list[Formula]:
    """Prompt for each candidate and return the ones marked for removal."""
    marked: dict[str, Formula] = {}
    i = 0
    while i < len(candidates):
        f = candidates[i]
        show(
            f,
            f"[{i + 1}/{len(candidates)}]",
            inventory,
            details,
            set(marked) - {f.name},
            f.name in marked,
        )
        while True:
            answer = ask("Remove? [y/N/b/i/q/?] ").strip().lower()
            if answer in ("i", "?"):
                if answer == "i":
                    subprocess.run(["brew", "info", f.name], check=False)
                else:
                    print(HELP)
                continue
            if answer in ("y", "n", "", "b", "q"):
                break
            print("Unknown answer. Options:\n" + HELP)
        print()
        if answer == "q":
            break
        if answer == "b":
            i = max(i - 1, 0)
            continue
        if answer == "y":
            marked[f.name] = f
        else:
            marked.pop(f.name, None)
        i += 1
    return list(marked.values())


def finish(
    selected: list[Formula],
    inventory: Inventory,
    details: DetailsLoader,
    ask: Ask = input,
    dry_run: bool = False,
) -> int:
    """Show the summary, confirm, then uninstall. Returns an exit code."""
    if not selected:
        print("Nothing marked for removal.")
        return 0
    names = [f.name for f in selected]
    freed = sorted(inventory.freed_by(set(names)))
    print(bold(f"Marked for removal ({len(names)}):"))
    for name in names:
        print(f"  {name}  {dim(format_size(details.size(name)))}")
    if freed:
        print(
            bold(f"Dependencies that `brew autoremove` should clean up ({len(freed)}):")
        )
        for name in freed:
            print(f"  {name}  {dim(format_size(details.size(name)))}")
    total = sum(details.size(n) for n in names + freed)
    print(f"Estimated space freed: {bold(format_size(total))}")

    commands = [["brew", "uninstall", *names], ["brew", "autoremove"]]
    if dry_run:
        print("\nDry run, would run:")
        for cmd in commands:
            print("  " + " ".join(cmd))
        return 0
    if ask("\nUninstall now? [y/N] ").strip().lower() != "y":
        print("Nothing removed.")
        return 0
    for cmd in commands:
        print(dim("$ " + " ".join(cmd)))
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            return result.returncode
    return 0


# --- Entry point -------------------------------------------------------------


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="brewreview",
        description=(
            "Review installed Homebrew formulae one by one and pick the ones to "
            "uninstall. Only leaves are shown: formulae no other installed "
            "formula depends on. Nothing is removed until you confirm at the end."
        ),
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="show what would be uninstalled instead of doing it",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {version('brewreview')}"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        inventory = load_inventory()
    except BrewError as e:
        print(f"brewreview: {e}", file=sys.stderr)
        return 1

    candidates = inventory.candidates()
    orphans = sum(not f.on_request for f in candidates)
    print(
        f"Reviewing {plural(len(candidates), 'leaf formula', 'leaf formulae')} "
        f"({len(candidates) - orphans} installed on request, "
        f"{plural(orphans, 'orphaned dependency', 'orphaned dependencies')}). "
        "Nothing is removed until you confirm at the end; '?' for help.\n"
    )

    details = DetailsLoader(inventory, candidates)
    try:
        selected = review(candidates, inventory, details)
        return finish(selected, inventory, details, dry_run=args.dry_run)
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.")
        return 130
    finally:
        details.close()
