# AGENTS.md — sshko

Guidance for AI agents (and humans) working on this repo.

## What this is

`sshko` is a **read-only** CLI for inspecting an SSH config (`~/.ssh/config`).
It is a single, dependency-free Python 3 file: [`sshko`](./sshko). There is no
build step and no third-party runtime dependency — only the standard library.

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
├── sshko        # the entire program (executable, #!/usr/bin/env python3)
├── README.md    # user-facing docs
├── AGENTS.md    # this file
└── .gitignore
```

Installed by symlinking the script onto PATH:
`ln -sf "$PWD/sshko" ~/.local/bin/sshko`.

## Architecture of `sshko`

The script is organized top-to-bottom into clear sections:

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

There is no test suite yet. The reliable way to test is against a throwaway
config dir, exercising includes, wildcards, and negation. Example:

```sh
TMP=$(mktemp -d); mkdir -p "$TMP/conf.d"
cat > "$TMP/config" <<'EOF'
Host *
    ForwardAgent yes
Host web-prod
    HostName 10.0.0.5
    User deploy
    Port 2222
Host web-* !web-old
    User www-data
Include conf.d/*.conf
EOF
cat > "$TMP/conf.d/extra.conf" <<'EOF'
Host db1 db-primary
    HostName db1.internal
    User postgres
EOF

./sshko --no-color --config "$TMP/config" list
./sshko --no-color --config "$TMP/config" search db
./sshko --no-color --config "$TMP/config" show web-prod
rm -rf "$TMP"
```

Expected: `list` shows `web-prod`, `db1`, `db-primary` (not `web-*` or `*`);
`web-prod` resolves to `deploy@10.0.0.5:2222` (its own block wins over the
`web-*` default). If you add tests, `pytest` is a sensible choice — add it as a
dev-only dependency, never a runtime one.

## When extending

- New read-only inspection subcommands are welcome (e.g. grouping, `--json`
  output, showing identity files, ping/reachability checks).
- Preserve the invariants above. If a feature would require writing config or
  launching arbitrary commands, surface the tradeoff to the user first.
