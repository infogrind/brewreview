import json
from datetime import UTC, datetime

import pytest
from conftest import FORMULAE, formula_json

from brewreview import brew


def test_parse_formula_basic_fields():
    f = brew.parse_formula(formula_json("me/tap/thing", deps=["x"]))
    assert f.name == "me/tap/thing"
    assert f.short_name == "thing"
    assert f.version == "1.0"
    assert f.on_request
    assert f.runtime_deps == ["x"]
    assert f.installed_at == datetime.fromtimestamp(1_700_000_000, UTC)
    assert f.deprecated is None and f.disabled is None


def test_parse_formula_prefers_linked_keg():
    data = formula_json("app")
    data["installed"] = [
        {"version": "1.0", "time": 1, "installed_on_request": False},
        {"version": "2.0", "time": 2, "installed_on_request": True},
    ]
    data["linked_keg"] = "1.0"
    f = brew.parse_formula(data)
    assert f.version == "1.0"
    assert not f.on_request


def test_parse_formula_deprecation():
    f = brew.parse_formula(
        formula_json("old", deprecated=True, deprecation_reason="unmaintained")
    )
    assert f.deprecated == "unmaintained"
    g = brew.parse_formula(formula_json("old", disabled=True, disable_reason=None))
    assert g.disabled == ""


def test_parse_formula_missing_time():
    f = brew.parse_formula(formula_json("app", time=None))
    assert f.installed_at is None


def test_candidates_requested_first_then_orphans(inventory):
    names = [f.name for f in inventory.candidates()]
    assert names == ["app", "me/tap/thing", "tool", "orphan"]


def test_freed_by_shared_dependency_is_kept(inventory):
    # tool still needs lib2, and keeper was installed on request.
    assert inventory.freed_by({"app"}) == {"lib1"}


def test_freed_by_everything_using_it_removed(inventory):
    assert inventory.freed_by({"app", "tool"}) == {"lib1", "lib2"}


def test_freed_by_nothing(inventory):
    assert inventory.freed_by({"orphan"}) == set()


def test_load_inventory(monkeypatch):
    outputs = {
        ("info", "--json=v2", "--installed"): json.dumps({"formulae": FORMULAE}),
        ("leaves",): "app\norphan\n",
        ("--cellar",): "/opt/homebrew/Cellar\n",
        ("--prefix",): "/opt/homebrew\n",
    }
    monkeypatch.setattr(brew, "run_brew", lambda *args: outputs[args])
    inv = brew.load_inventory()
    assert inv.leaves == ["app", "orphan"]
    assert set(inv.formulae) == {f["full_name"] for f in FORMULAE}
    assert str(inv.cellar) == "/opt/homebrew/Cellar"


def test_run_brew_failure_raises(monkeypatch):
    monkeypatch.setenv("PATH", "")
    with pytest.raises(brew.BrewError, match="not found"):
        brew.run_brew("--version")
