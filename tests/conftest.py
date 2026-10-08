"""Shared fixtures: a small fake Homebrew installation."""

import pytest

from brewreview.brew import Inventory, parse_formula


def formula_json(name, *, on_request=True, deps=(), time=1_700_000_000, **extra):
    """One entry shaped like `brew info --json=v2` output."""
    return {
        "name": name.rsplit("/", 1)[-1],
        "full_name": name,
        "desc": f"The {name} tool",
        "homepage": f"https://example.com/{name}",
        "linked_keg": "1.0",
        "deprecated": False,
        "disabled": False,
        "installed": [
            {
                "version": "1.0",
                "time": time,
                "installed_on_request": on_request,
                "runtime_dependencies": [{"full_name": d} for d in deps],
            }
        ],
        **extra,
    }


# app  -> lib1 -> lib2   (lib2 is a transitive runtime dependency of app)
# tool -> lib2
# orphan: a leftover dependency nothing needs any more
# keeper: a library you installed yourself; never freed automatically
FORMULAE = [
    formula_json("app", deps=["lib1", "lib2", "keeper"]),
    formula_json("tool", deps=["lib2"]),
    formula_json("lib1", on_request=False, deps=["lib2"]),
    formula_json("lib2", on_request=False),
    formula_json("keeper"),
    formula_json("orphan", on_request=False),
    formula_json("me/tap/thing"),
]


@pytest.fixture
def inventory(tmp_path):
    formulae = [parse_formula(f) for f in FORMULAE]
    return Inventory(
        formulae={f.name: f for f in formulae},
        leaves=["app", "me/tap/thing", "orphan", "tool"],
        cellar=tmp_path / "Cellar",
        prefix=tmp_path,
    )


class FakeDetails:
    """Stands in for DetailsLoader without touching the disk."""

    def size(self, name):
        return 1024 * 1024

    def last_used(self, name):
        return None

    def close(self):
        pass


@pytest.fixture
def details():
    return FakeDetails()
