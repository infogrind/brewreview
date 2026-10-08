from datetime import UTC, datetime, timedelta

import pytest

from brewreview import cli


def scripted(*answers):
    """An `ask` function that replays answers, failing if it runs out."""
    remaining = list(answers)

    def ask(prompt):
        if not remaining:
            raise AssertionError(f"unexpected prompt: {prompt}")
        return remaining.pop(0)

    return ask


@pytest.mark.parametrize(
    ("n", "expected"),
    [(0, "0 B"), (1023, "1023 B"), (1536, "1.5 KB"), (5 * 1024**3, "5.0 GB")],
)
def test_format_size(n, expected):
    assert cli.format_size(n) == expected


@pytest.mark.parametrize(
    ("days", "expected"),
    [(0, "today"), (1, "1 day ago"), (10, "1 week ago"), (400, "1 year ago")],
)
def test_format_ago(days, expected):
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert cli.format_ago(now - timedelta(days=days), now) == expected


def test_format_ago_unknown():
    assert cli.format_ago(None) == "unknown"


def test_review_collects_answers(inventory, details):
    # app: y, me/tap/thing: Enter (keep), tool: n, orphan: y
    selected = cli.review(
        inventory.candidates(), inventory, details, scripted("y", "", "n", "Y")
    )
    assert [f.name for f in selected] == ["app", "orphan"]


def test_review_back_changes_earlier_answer(inventory, details):
    # app: y, then go back from me/tap/thing and change app to n, then quit.
    selected = cli.review(
        inventory.candidates(), inventory, details, scripted("y", "b", "n", "q")
    )
    assert selected == []


def test_review_help_and_unknown_reprompt(inventory, details, capsys):
    selected = cli.review(
        inventory.candidates(), inventory, details, scripted("?", "what", "y", "q")
    )
    assert [f.name for f in selected] == ["app"]
    assert capsys.readouterr().out.count("mark for removal") == 2


def test_review_shows_freed_dependencies(inventory, details, capsys):
    cli.review(inventory.candidates(), inventory, details, scripted("q"))
    out = capsys.readouterr().out
    assert "app 1.0" in out
    assert "also frees 1 dependency (1.0 MB): lib1" in out


def test_finish_nothing_selected(inventory, details, capsys):
    assert cli.finish([], inventory, details, scripted()) == 0
    assert "Nothing marked" in capsys.readouterr().out


def test_finish_dry_run(inventory, details, capsys):
    selected = [inventory.formulae["app"], inventory.formulae["tool"]]
    assert cli.finish(selected, inventory, details, scripted(), dry_run=True) == 0
    out = capsys.readouterr().out
    assert "brew uninstall app tool" in out
    assert "lib1" in out and "lib2" in out
    assert "Estimated space freed: 4.0 MB" in out


def test_finish_declined(inventory, details, monkeypatch, capsys):
    monkeypatch.setattr(cli.subprocess, "run", pytest.fail)
    selected = [inventory.formulae["app"]]
    assert cli.finish(selected, inventory, details, scripted("")) == 0
    assert "Nothing removed" in capsys.readouterr().out


def test_finish_confirmed_runs_brew(inventory, details, monkeypatch):
    calls = []

    class Result:
        returncode = 0

    monkeypatch.setattr(
        cli.subprocess, "run", lambda cmd, check: calls.append(cmd) or Result()
    )
    selected = [inventory.formulae["app"]]
    assert cli.finish(selected, inventory, details, scripted("y")) == 0
    assert calls == [["brew", "uninstall", "app"], ["brew", "autoremove"]]


def test_main_aborts_cleanly_on_ctrl_c(inventory, details, monkeypatch, capsys):
    monkeypatch.setattr(cli, "load_inventory", lambda: inventory)
    monkeypatch.setattr(cli, "DetailsLoader", lambda inv, order: details)

    def interrupt(*args):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "review", interrupt)
    assert cli.main([]) == 130
    assert "Aborted" in capsys.readouterr().out


def test_main_reports_brew_errors(monkeypatch, capsys):
    def fail():
        raise cli.BrewError("boom")

    monkeypatch.setattr(cli, "load_inventory", fail)
    assert cli.main([]) == 1
    assert "boom" in capsys.readouterr().err
