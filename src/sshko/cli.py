"""sshko - a small, read-only manager for your SSH config.

It inspects (never modifies) your ~/.ssh/config:
  - list            enumerate every configured Host
  - show <host>     print the fully-resolved config for one host
  - search <term>   fuzzy/substring search over aliases, hostnames, users
  - connect <host>  launch `ssh <host>` (no config writes; just spawns ssh)
  - pick            interactive picker, then connect

The only thing sshko ever executes is `ssh` itself (for `show` resolution and
for `connect`). It opens the config files strictly for reading.
"""

import argparse
import fnmatch
import glob
import os
import shutil
import subprocess
import sys

DEFAULT_CONFIG = os.path.expanduser("~/.ssh/config")
SSH_DIR = os.path.expanduser("~/.ssh")

# Glob metacharacters that mark a Host pattern as a wildcard (a "defaults"
# block) rather than a concrete, connectable host alias.
WILDCARD_CHARS = set("*?[]")


# ---------------------------------------------------------------------------
# Color helpers (auto-disabled when stdout is not a TTY or NO_COLOR is set).
# ---------------------------------------------------------------------------
class Style:
    def __init__(self, enabled):
        self.enabled = enabled

    def _wrap(self, code, text):
        if not self.enabled:
            return text
        return f"\033[{code}m{text}\033[0m"

    def bold(self, t):
        return self._wrap("1", t)

    def dim(self, t):
        return self._wrap("2", t)

    def cyan(self, t):
        return self._wrap("36", t)

    def green(self, t):
        return self._wrap("32", t)

    def yellow(self, t):
        return self._wrap("33", t)


def make_style(no_color):
    enabled = (not no_color) and sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
    return Style(enabled)


# ---------------------------------------------------------------------------
# Config model + parser.
# ---------------------------------------------------------------------------
class HostBlock:
    """A single `Host` stanza: its patterns, options, and source location."""

    def __init__(self, patterns, source_file, line_no):
        self.patterns = patterns            # e.g. ["web-*", "!web-old"]
        self.options = {}                   # lower-cased key -> first value seen
        self.source_file = source_file
        self.line_no = line_no

    @property
    def is_wildcard(self):
        # A block is a "defaults" block if every one of its (positive) patterns
        # contains glob metacharacters - i.e. there is no concrete alias to list.
        positives = [p for p in self.patterns if not p.startswith("!")]
        if not positives:
            return True
        return all(any(c in WILDCARD_CHARS for c in p) for p in positives)

    @property
    def aliases(self):
        # Concrete (non-wildcard, non-negated) aliases a user could connect to.
        return [
            p for p in self.patterns
            if not p.startswith("!") and not any(c in WILDCARD_CHARS for c in p)
        ]

    def matches(self, host):
        """SSH semantics: matches if `host` hits >=1 positive pattern and 0 negated ones."""
        matched_positive = False
        for pat in self.patterns:
            if pat.startswith("!"):
                if fnmatch.fnmatch(host, pat[1:]):
                    return False            # a negated pattern always vetoes
            elif fnmatch.fnmatch(host, pat):
                matched_positive = True
        return matched_positive


def _split_keyword(line):
    """Split a config line into (keyword, value), supporting `key value` and `key=value`."""
    stripped = line.strip()
    if "=" in stripped and (
        # `=` form only when it appears before any space, e.g. `Port=2222`
        "=" in stripped.split(None, 1)[0]
    ):
        key, _, value = stripped.partition("=")
        return key.strip(), value.strip()
    parts = stripped.split(None, 1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def _resolve_include(value, current_file):
    """Expand an Include directive into concrete file paths.

    Per ssh_config(5): relative paths are taken relative to ~/.ssh for the user
    config (and to the dir of the containing file for included files). We also
    expand `~` and shell globs.
    """
    paths = []
    for token in value.split():
        token = os.path.expanduser(token)
        if not os.path.isabs(token):
            base = SSH_DIR if os.path.dirname(current_file) == SSH_DIR else os.path.dirname(current_file)
            token = os.path.join(base, token)
        # sorted() keeps include ordering deterministic across runs.
        paths.extend(sorted(glob.glob(token)))
    return paths


def parse_config(path, _seen=None):
    """Parse a config file into an ordered list of HostBlock, following Include."""
    if _seen is None:
        _seen = set()
    real = os.path.realpath(path)
    if real in _seen or not os.path.isfile(path):
        return []                           # guard against include cycles / missing files
    _seen.add(real)

    blocks = []
    current = None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return blocks

    for idx, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        keyword, value = _split_keyword(line)
        kw = keyword.lower()

        if kw == "include":
            # Inline the included file's blocks at this position.
            for inc in _resolve_include(value, path):
                blocks.extend(parse_config(inc, _seen))
            continue

        if kw == "host":
            current = HostBlock(value.split(), path, idx)
            blocks.append(current)
            continue

        if kw == "match":
            # Match blocks are conditional and resolved by `ssh -G` at show time;
            # we don't enumerate them as listable hosts. Stop attaching options.
            current = None
            continue

        if current is not None:
            current.options.setdefault(kw, value)

    return blocks


# ---------------------------------------------------------------------------
# Summary resolution (fast, parser-based - used for list/search).
# ---------------------------------------------------------------------------
def resolve_summary(alias, blocks):
    """Resolve user/hostname/port for an alias the way ssh would (first value wins)."""
    resolved = {}
    for block in blocks:
        if block.matches(alias):
            for key, val in block.options.items():
                resolved.setdefault(key, val)
    return {
        "hostname": resolved.get("hostname", alias),
        "user": resolved.get("user"),
        "port": resolved.get("port", "22"),
        "identityfile": resolved.get("identityfile"),
    }


def collect_hosts(blocks):
    """Return ordered, de-duplicated concrete aliases plus their source block."""
    seen = set()
    hosts = []
    for block in blocks:
        for alias in block.aliases:
            if alias not in seen:
                seen.add(alias)
                hosts.append((alias, block))
    return hosts


def _format_target(summary):
    """Render a summary dict as `user@hostname:port` (omitting defaults)."""
    target = summary["hostname"]
    if summary["user"]:
        target = f"{summary['user']}@{target}"
    if summary["port"] and summary["port"] != "22":
        target += f":{summary['port']}"
    return target


# ---------------------------------------------------------------------------
# Commands.
# ---------------------------------------------------------------------------
def cmd_list(args, st):
    blocks = parse_config(args.config)
    hosts = collect_hosts(blocks)
    if not hosts:
        print(st.dim("No hosts found in " + args.config))
        return 0

    rows = [(alias, _format_target(resolve_summary(alias, blocks))) for alias, _ in hosts]

    width = max(len(a) for a, _ in rows)
    for alias, target in rows:
        print(f"{st.cyan(alias.ljust(width))}  {st.dim('→')}  {target}")
    print(st.dim(f"\n{len(rows)} host(s) in {args.config}"))
    return 0


def cmd_search(args, st):
    blocks = parse_config(args.config)
    hosts = collect_hosts(blocks)
    term = args.term.lower()

    matches = []
    for alias, _ in hosts:
        s = resolve_summary(alias, blocks)
        haystack = " ".join(
            filter(None, [alias, s["hostname"], s["user"], s["port"]])
        ).lower()
        if term in haystack:
            matches.append((alias, s))

    if not matches:
        print(st.dim(f"No hosts matching '{args.term}'"))
        return 1

    width = max(len(a) for a, _ in matches)
    for alias, s in matches:
        print(f"{st.cyan(alias.ljust(width))}  {st.dim('→')}  {_format_target(s)}")
    return 0


def cmd_show(args, st):
    blocks = parse_config(args.config)

    # Locate the defining block so we can report where it lives.
    source = None
    for alias, block in collect_hosts(blocks):
        if alias == args.host:
            source = block
            break

    if source is not None:
        rel = source.source_file.replace(os.path.expanduser("~"), "~")
        print(st.bold(args.host) + st.dim(f"  ({rel}:{source.line_no})"))
    else:
        print(st.bold(args.host) + st.dim("  (not a literal Host entry; resolving via wildcards)"))

    # `ssh -G` gives the authoritative fully-resolved config (wildcards, Match,
    # defaults included). Read-only: it computes config without connecting.
    ssh = shutil.which("ssh")
    if not ssh:
        print(st.yellow("ssh not found on PATH; cannot resolve full config."))
        return 1

    ssh_cmd = [ssh]
    if os.path.isfile(args.config):
        ssh_cmd += ["-F", args.config]      # resolve against the config we're inspecting
    ssh_cmd += ["-G", args.host]
    try:
        out = subprocess.run(
            ssh_cmd, capture_output=True, text=True, check=True,
        ).stdout
    except subprocess.CalledProcessError as exc:
        print(st.yellow(f"ssh -G failed: {exc.stderr.strip()}"))
        return 1

    # Surface the most useful keys first, then everything else.
    primary = ["hostname", "port", "user", "identityfile", "proxyjump",
               "proxycommand", "forwardagent", "localforward", "remoteforward"]
    parsed = {}
    for ln in out.splitlines():
        k, _, v = ln.partition(" ")
        parsed.setdefault(k.lower(), []).append(v)

    print()
    for key in primary:
        if key in parsed:
            for v in parsed[key]:
                print(f"  {st.green(key.ljust(14))} {v}")
    if args.all:
        print(st.dim("\n  --- all resolved options ---"))
        for key in sorted(parsed):
            if key in primary:
                continue
            for v in parsed[key]:
                print(f"  {st.dim(key.ljust(14))} {v}")
    else:
        print(st.dim("\n  (use --all to see every resolved option)"))
    return 0


def cmd_connect(args, st):
    # Pure passthrough to ssh - sshko never edits config, it just launches the client.
    ssh = shutil.which("ssh")
    if not ssh:
        print(st.yellow("ssh not found on PATH."), file=sys.stderr)
        return 1
    cmd = [ssh, args.host] + (args.ssh_args or [])
    print(st.dim("→ " + " ".join(cmd)))
    os.execv(ssh, cmd)             # replace this process with ssh


def cmd_pick(args, st):
    blocks = parse_config(args.config)
    hosts = [alias for alias, _ in collect_hosts(blocks)]
    if not hosts:
        print(st.dim("No hosts to pick from."))
        return 1

    chosen = None
    fzf = shutil.which("fzf")
    if fzf and sys.stdin.isatty():
        # Prefer fzf for a fuzzy interactive experience when available.
        proc = subprocess.run(
            [fzf, "--prompt", "ssh> ", "--height", "40%", "--reverse"],
            input="\n".join(hosts), text=True, capture_output=True,
        )
        chosen = proc.stdout.strip() or None
    else:
        for i, h in enumerate(hosts, start=1):
            print(f"  {st.dim(str(i).rjust(3))}  {st.cyan(h)}")
        try:
            raw = input(st.bold("\nSelect host (number or name): ")).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 130
        if raw.isdigit() and 1 <= int(raw) <= len(hosts):
            chosen = hosts[int(raw) - 1]
        elif raw in hosts:
            chosen = raw

    if not chosen:
        print(st.dim("Nothing selected."))
        return 1

    args.host = chosen
    args.ssh_args = []
    return cmd_connect(args, st)


# ---------------------------------------------------------------------------
# CLI wiring.
# ---------------------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(
        prog="sshko",
        description="Read-only manager/inspector for your SSH config.",
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG,
                        help=f"Path to ssh config (default: {DEFAULT_CONFIG})")
    parser.add_argument("--no-color", action="store_true", help="Disable colored output")

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="List all configured hosts")

    p_show = sub.add_parser("show", help="Show fully-resolved config for a host")
    p_show.add_argument("host")
    p_show.add_argument("--all", action="store_true", help="Show every resolved option")

    p_search = sub.add_parser("search", help="Search hosts by alias/hostname/user")
    p_search.add_argument("term")

    p_conn = sub.add_parser("connect", help="Connect to a host (launches ssh)")
    p_conn.add_argument("host")
    p_conn.add_argument("ssh_args", nargs=argparse.REMAINDER,
                        help="Extra args passed through to ssh")

    sub.add_parser("pick", help="Interactively pick a host and connect")

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    st = make_style(args.no_color)

    # No subcommand → behave like the interactive picker.
    if not args.command:
        return cmd_pick(args, st)

    dispatch = {
        "list": cmd_list,
        "show": cmd_show,
        "search": cmd_search,
        "connect": cmd_connect,
        "pick": cmd_pick,
    }
    return dispatch[args.command](args, st)


if __name__ == "__main__":
    sys.exit(main())
