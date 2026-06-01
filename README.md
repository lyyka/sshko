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

The script is a single, dependency-free Python 3 file. It's already symlinked to
`~/.local/bin/sshko` (on your PATH). To reinstall elsewhere:

```sh
ln -sf /Users/lukarobajac/Projects/sshko/sshko ~/.local/bin/sshko
```

Optional: install [`fzf`](https://github.com/junegunn/fzf) (`brew install fzf`)
for fuzzy interactive picking; otherwise `pick` falls back to a numbered menu.
