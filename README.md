# sshko

A small, **read-only** CLI manager/inspector for your SSH config (`~/.ssh/config`).

It never writes to or edits your config. The only program it ever executes is
`ssh` itself — for resolving config (`ssh -G`) and for `connect`.

## Commands

```
sshko list                 # list every configured host (alias → user@hostname:port)
sshko show <host>          # fully-resolved config for one host (via `ssh -G`)
sshko show <host> --all    # ...including every resolved option
sshko search <term>        # substring search over aliases, hostnames, users
sshko connect <host> [...] # launch `ssh <host>` (extra args passed through)
sshko pick                 # interactive picker (uses fzf if installed), then connect
sshko                      # same as `pick`
```

Global flags: `--config <path>` (default `~/.ssh/config`), `--no-color`.

## Features

- **Include support** — follows `Include` directives (with `~` expansion and globs)
  so hosts defined in included files show up too.
- **SSH-accurate resolution** — `list`/`search` apply wildcard and negated
  (`!pattern`) blocks with first-value-wins semantics, matching ssh's behavior;
  `show` defers to `ssh -G` for the authoritative, fully-resolved set.
- **Wildcard-aware** — pure-wildcard stanzas (e.g. `Host *`) are treated as
  defaults and excluded from the host list.

## Install

sshko is a dependency-free Python 3 tool (standard library only). Pick whichever
install style suits you.

### With uv (recommended)

```sh
uv tool install .            # exposes `sshko` globally
# or run without installing:
uvx --from . sshko list
# or inside the project:
uv run sshko list
```

### Zero-install (symlink the launcher)

The repo ships a self-contained launcher that needs no install or `uv` — it just
needs `python3`:

```sh
ln -sf "$PWD/sshko" ~/.local/bin/sshko   # anywhere on your PATH
```

### Optional

Install [`fzf`](https://github.com/junegunn/fzf) (`brew install fzf`) for fuzzy
interactive picking; otherwise `pick` falls back to a numbered menu.

## Development

```sh
uv run pytest          # run the test suite
uv sync                # set up the dev environment (installs pytest)
```

Without uv: `python -m venv .venv && .venv/bin/pip install pytest && .venv/bin/python -m pytest`.
