"""Tests for the config model + parser (the pure, ssh-free core)."""

import textwrap

import pytest

from sshko.cli import (
    HostBlock,
    _format_target,
    _resolve_include,
    _split_keyword,
    collect_hosts,
    parse_config,
    resolve_summary,
)


# --- _split_keyword --------------------------------------------------------
@pytest.mark.parametrize("line, expected", [
    ("HostName example.com", ("HostName", "example.com")),
    ("Port=2222", ("Port", "2222")),
    ("  User   deploy  ", ("User", "deploy")),
    ("IdentityFile ~/.ssh/id_ed25519", ("IdentityFile", "~/.ssh/id_ed25519")),
    ("ForwardAgent", ("ForwardAgent", "")),
])
def test_split_keyword(line, expected):
    assert _split_keyword(line) == expected


def test_split_keyword_value_with_spaces_is_preserved():
    # ProxyCommand carries a whole command line as its value.
    key, value = _split_keyword("ProxyCommand ssh -W %h:%p bastion")
    assert key == "ProxyCommand"
    assert value == "ssh -W %h:%p bastion"


# --- HostBlock -------------------------------------------------------------
def test_is_wildcard_for_pure_glob():
    assert HostBlock(["*"], "f", 1).is_wildcard is True
    assert HostBlock(["web-*"], "f", 1).is_wildcard is True


def test_is_wildcard_false_for_concrete_alias():
    assert HostBlock(["web-prod"], "f", 1).is_wildcard is False


def test_aliases_excludes_globs_and_negations():
    block = HostBlock(["web-*", "!web-old", "web-prod"], "f", 1)
    assert block.aliases == ["web-prod"]


@pytest.mark.parametrize("host, expected", [
    ("web-prod", True),       # matches web-*
    ("web-staging", True),
    ("web-old", False),       # vetoed by negation
    ("db1", False),           # no positive match
])
def test_matches_with_negation(host, expected):
    block = HostBlock(["web-*", "!web-old"], "f", 1)
    assert block.matches(host) is expected


# --- _resolve_include ------------------------------------------------------
def test_resolve_include_globs_relative_to_including_file(tmp_path):
    conf_d = tmp_path / "conf.d"
    conf_d.mkdir()
    (conf_d / "a.conf").write_text("")
    (conf_d / "b.conf").write_text("")
    including = str(tmp_path / "config")

    resolved = _resolve_include("conf.d/*.conf", including)

    assert resolved == [str(conf_d / "a.conf"), str(conf_d / "b.conf")]


# --- parse_config ----------------------------------------------------------
def test_parse_follows_includes(sample_config):
    blocks = parse_config(sample_config)
    aliases = [a for a, _ in collect_hosts(blocks)]
    # web-prod from main file; db1/db-primary from the included file.
    assert aliases == ["web-prod", "db1", "db-primary"]


def test_parse_records_source_location(sample_config):
    blocks = parse_config(sample_config)
    by_alias = {a: b for a, b in collect_hosts(blocks)}
    assert by_alias["web-prod"].source_file == sample_config
    assert by_alias["web-prod"].line_no == 6  # line of `Host web-prod`


def test_parse_skips_match_blocks(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text(textwrap.dedent("""\
        Match host *.internal
            User svc

        Host real
            HostName 1.2.3.4
    """))
    blocks = parse_config(str(cfg))
    # Only the real Host stanza is enumerable; Match is left to `ssh -G`.
    assert [a for a, _ in collect_hosts(blocks)] == ["real"]


def test_parse_missing_file_returns_empty(tmp_path):
    assert parse_config(str(tmp_path / "nope")) == []


def test_parse_handles_include_cycle(tmp_path):
    # a includes b, b includes a — must terminate, not recurse forever.
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text(f"Host ha\n    HostName 1.1.1.1\nInclude {b}\n")
    b.write_text(f"Host hb\n    HostName 2.2.2.2\nInclude {a}\n")
    blocks = parse_config(str(a))
    assert [bl.patterns[0] for bl in blocks] == ["ha", "hb"]


# --- resolve_summary -------------------------------------------------------
def test_resolve_summary_first_value_wins(sample_config):
    # web-prod sets User=deploy before the web-* default (www-data) applies.
    s = resolve_summary("web-prod", parse_config(sample_config))
    assert s["user"] == "deploy"
    assert s["hostname"] == "10.0.0.5"
    assert s["port"] == "2222"


def test_resolve_summary_inherits_from_wildcard(sample_config):
    # web-staging has no own block: it inherits www-data + web_key from web-*.
    s = resolve_summary("web-staging", parse_config(sample_config))
    assert s["user"] == "www-data"
    assert s["identityfile"] == "~/.ssh/web_key"


def test_resolve_summary_defaults_hostname_to_alias(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text("Host bare\n    User me\n")
    s = resolve_summary("bare", parse_config(str(cfg)))
    assert s["hostname"] == "bare"
    assert s["port"] == "22"


# --- collect_hosts ---------------------------------------------------------
def test_collect_hosts_dedupes_preserving_order(tmp_path):
    cfg = tmp_path / "config"
    cfg.write_text(textwrap.dedent("""\
        Host alpha
            HostName 1.1.1.1
        Host alpha
            User dup
        Host beta
            HostName 2.2.2.2
    """))
    assert [a for a, _ in collect_hosts(parse_config(str(cfg)))] == ["alpha", "beta"]


# --- _format_target --------------------------------------------------------
@pytest.mark.parametrize("summary, expected", [
    ({"hostname": "h", "user": None, "port": "22"}, "h"),
    ({"hostname": "h", "user": "u", "port": "22"}, "u@h"),
    ({"hostname": "h", "user": "u", "port": "2222"}, "u@h:2222"),
    ({"hostname": "h", "user": None, "port": "2222"}, "h:2222"),
])
def test_format_target(summary, expected):
    assert _format_target(summary) == expected
