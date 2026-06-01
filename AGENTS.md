# AGENTS.md — sshko

Guidance for AI agents (and humans) working on this repo.

## What this is

`sshko` is a **read-only** CLI for inspecting an SSH config (`~/.ssh/config`).
It is a dependency-free Python 3 package (standard library only). All program
logic lives in one module, [`src/sshko/cli.py`](./src/sshko/cli.py); everything
else is packaging, a launcher, and tests. There is no third-party runtime
dependency.

## Hard invariants (do not break these)

1. **Read-only.** sshko must never write to, create, or edit any SSH config
   file. Config files are opened with mode `"r"` only. Any change that adds
   write/edit capability to the config is out of scope for this tool — push
   back rather than implement it.
2. **The only process it launches is `ssh`.** Specifically:
   - `ssh -G <host>` (config resolution, in `cmd_show`) — does not connect.
   - `ssh <host> [args]` (in `cmd_connect`, via `os.execv`) — launches a session.
   - `fzf` is optionally invoked in `cmd_pick` for interactive selection.
   Do not shell out to anything else without a clear reason.
3. **Zero runtime dependencies.** Standard library only, so it runs anywhere
   `python3` exists. `fzf` is an *optional* convenience with a built-in fallback.

## Layout

```
sshko/
├── src/sshko/
│   ├── __init__.py    # exposes main(), __version__
│   ├── __main__.py    # enables `python -m sshko`
│   └── cli.py         # ALL program logic lives here
├── tests/
│   ├── conftest.py    # fixtures: plain_style, sample_config
│   ├── test_parser.py # pure parser/model/resolution tests
│   └── test_commands.py # output tests for ssh-free commands
├── sshko              # zero-install launcher (executable) -> src/sshko/cli.py
├── pyproject.toml     # packaging + entry point + pytest config (uv-friendly)
├── README.md          # user-facing docs
├── AGENTS.md          # this file
└── .gitignore
```

Three ways to run it, all calling the same `sshko.cli:main`:
- **uv:** `uv tool install .`, `uvx --from . sshko`, or `uv run sshko`.
- **Zero-install launcher:** the top-level `sshko` script adds `src/` to
  `sys.path` then calls `main()` — works via a PATH symlink without any install
  (`ln -sf "$PWD/sshko" ~/.local/bin/sshko`). Used because `uv` may be absent.
- **Module:** `python -m sshko`.

## Architecture of `src/sshko/cli.py`

The module is organized top-to-bottom into clear sections:

- **`Style` / `make_style`** — TTY-aware ANSI coloring. Auto-disabled when stdout
  is not a TTY, when `--no-color` is passed, or when `NO_COLOR` is set.

- **Config model + parser**
  - `HostBlock` — one `Host` stanza: its `patterns`, an ordered `options` dict
    (lower-cased keys, **first value wins** to mirror ssh), and `source_file` /
    `line_no` for provenance.
    - `is_wildcard` — true when every positive pattern contains glob metachars
      (`* ? [ ]`); such blocks are config *defaults* (e.g. `Host *`), not
      connectable aliases.
    - `aliases` — concrete, non-negated, non-glob patterns (the listable hosts).
    - `matches(host)` — ssh semantics: matches if `host` hits ≥1 positive pattern
      and 0 negated (`!pattern`) patterns. A negated pattern always vetoes.
  - `_split_keyword` — splits a line into `(keyword, value)`, supporting both
    `Key value` and `Key=value` forms.
  - `_resolve_include` — expands an `Include` directive: `~` expansion, globs,
    and relative-path resolution (relative to `~/.ssh` for the top-level user
    config, else to the including file's directory), per `ssh_config(5)`.
  - `parse_config(path)` — returns an ordered `list[HostBlock]`, recursively
    inlining `Include`d files at their position. Guards against include cycles
    and missing files via a `_seen` realpath set. `Match` blocks are **not**
    enumerated (they're conditional); they stop option attachment and are left
    to `ssh -G` to resolve at show time.

- **Summary resolution (fast, parser-based — used by `list`/`search`)**
  - `resolve_summary(alias, blocks)` — walks all matching blocks in order and
    takes the first value seen for each key (ssh-accurate), returning hostname /
    user / port / identityfile.
  - `collect_hosts(blocks)` — ordered, de-duplicated `(alias, defining_block)`.
  - `_format_target(summary)` — renders a summary as `user@hostname:port`,
    omitting an absent user and the default port 22.

- **Commands** — `cmd_list`, `cmd_search`, `cmd_show`, `cmd_connect`, `cmd_pick`.
  - `cmd_show` is the one place that trusts `ssh -G` for the **authoritative**
    fully-resolved config (handles wildcards, `Match`, and built-in defaults).
    It passes `-F <config>` when the inspected config file exists so a custom
    `--config` is honored. It prints a curated set of primary keys first, then
    everything else under `--all`.
  - `cmd_connect` replaces the process with ssh via `os.execv`.
  - `cmd_pick` prefers `fzf`; falls back to a numbered stdin menu.

- **CLI wiring** — `build_parser` (argparse subcommands) and `main`, which
  dispatches by subcommand. No subcommand → `cmd_pick`.

## Conventions

- 4-space indentation; blank lines separating logical blocks.
- Comment any non-obvious logic (pattern matching, include resolution, first-
  value-wins, `os.execv`) explaining *why*.
- Keep it a single file. Only split into a package if it genuinely outgrows one
  file; duplication is acceptable over premature abstraction.

## Testing

Tests live in `tests/` and use `pytest`. They cover the pure, ssh-free core
(parsing, includes, wildcard/negation matching, first-value-wins resolution,
de-duplication, target formatting) plus the output of the ssh-free commands
(`list`, `search`) via `capsys`. They deliberately do **not** test `cmd_show`
(needs a real `ssh -G`) or `cmd_connect` (`os.execv`).

Run them:

```sh
uv run pytest
# or, without uv:
python -m venv .venv && .venv/bin/pip install pytest && .venv/bin/python -m pytest
```

`pythonpath = ["src"]` in `pyproject.toml` makes `import sshko` work in tests
without an install step. Key fixtures (`tests/conftest.py`): `plain_style`
(coloring off, so assertions match raw text) and `sample_config` (a tmp config
exercising includes/wildcards/negation).

When adding behavior, add a test in the matching file. Keep `pytest` a
**dev-only** dependency (`[dependency-groups].dev`) — never a runtime one.

## When extending

- New read-only inspection subcommands are welcome (e.g. grouping, `--json`
  output, showing identity files, ping/reachability checks).
- Preserve the invariants above. If a feature would require writing config or
  launching arbitrary commands, surface the tradeoff to the user first.
