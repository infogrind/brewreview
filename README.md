# brewreview

Periodically review the Homebrew formulae you have installed and uninstall the
ones you no longer need.

`brewreview` walks through your installed formulae one at a time and shows what
each one is, when you installed it, how big it is and when you last ran it. You
mark the ones to remove as you go. Nothing is uninstalled until the end, when
you see a summary and confirm once.

```
[3/41] bower 1.8.14  (installed on request)
  Package manager for the web
  https://bower.io/
  Installed 2025-04-06 (1 year ago) · 35.4 MB · last run: 1 year ago
Remove? [y/N/b/i/q/?]
```

## Installation

```sh
brew install infogrind/tap/brewreview
```

Or from a checkout: `uv run brewreview`.

## Usage

```sh
brewreview            # review, then confirm and uninstall
brewreview --dry-run  # review, then only print what would be run
```

At each prompt:

| Key | Action |
| ----------- | ----------------------------------------- |
| `y` | mark for removal |
| `n` / Enter | keep |
| `b` | go back to the previous formula |
| `i` | show the full `brew info` output |
| `q` | stop reviewing and go to the summary |
| `?` | show help |

Ctrl-C at any point before the final confirmation exits without changing
anything. Decisions aren't saved between runs, so each review starts fresh.

After you confirm, `brewreview` runs `brew uninstall` on your selection,
followed by `brew autoremove` to clean up dependencies nothing needs any more.

## Which formulae are shown

Only *leaves*: formulae that no other installed formula depends on (what
`brew leaves` lists). Anything else is still needed and can't be removed
safely, so it's not offered.

Leaves come in two kinds, labelled in the output and shown in this order:

- **installed on request**: you ran `brew install <name>` yourself
  (`brew leaves --installed-on-request`, or `-r`).
- **orphaned dependency**: it was installed because another formula needed
  it, but that formula has since been removed
  (`brew leaves --installed-as-dependency`, or `-p`). Usually safe to remove,
  though some stay around because Homebrew still keeps them as build
  dependencies.

## What the details mean

- **Installed**: when the installed version was poured. Upgrades reset this, so
  it's really "last installed or upgraded".
- **Size**: disk space used by the formula's directory in the Cellar.
- **Last run**: the latest access time of the formula's executables. macOS
  updates this when a program runs, though only about once a day, so it's
  approximate. Libraries have no executables and show `n/a`.
- **Also frees**: dependencies that would be orphaned by removing this formula,
  taking into account what you've already marked. `brew autoremove` removes
  them at the end. This is an estimate; Homebrew has a few extra rules (e.g.
  for build dependencies).
- **Deprecated / Disabled upstream**: Homebrew has deprecated the formula. That
  is a strong hint it's time to switch to something else.

## How it works

Startup takes about a second. Instead of calling `brew info` once per formula
(roughly a second each), `brewreview` gets everything from one
`brew info --json=v2 --installed` call, run in parallel with `brew leaves`.

Computing disk usage means walking every keg, which is slower, so it runs on a
background thread pool while you answer prompts. The formula on screen is
handled first, so its details are almost always ready by the time you see it.

| Module | Responsibility |
| ------------- | ------------------------------------------------------- |
| `brew.py` | Querying Homebrew; leaves; working out freed dependencies |
| `details.py` | Disk usage and last-run times, computed in the background |
| `cli.py` | The prompt loop, summary and uninstall |

## Development

```sh
uv run pytest
uv run ruff check .
```

Releases are published to `infogrind/tap` with `pythonformula`.

See [IDEAS.md](IDEAS.md) for possible future additions.
