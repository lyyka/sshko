"""Tests for the command layer's output (the ssh-free commands)."""

import argparse

from sshko.cli import cmd_list, cmd_search


def _args(**kw):
    ns = argparse.Namespace(config=None, no_color=True)
    ns.__dict__.update(kw)
    return ns


def test_cmd_list_outputs_resolved_targets(sample_config, plain_style, capsys):
    rc = cmd_list(_args(config=sample_config), plain_style)
    out = capsys.readouterr().out

    assert rc == 0
    assert "web-prod" in out and "deploy@10.0.0.5:2222" in out
    assert "postgres@db1.internal" in out
    # Wildcard/default stanzas are not listed as hosts.
    assert "web-*" not in out
    assert "3 host(s)" in out


def test_cmd_list_empty_config(tmp_path, plain_style, capsys):
    empty = tmp_path / "config"
    empty.write_text("# nothing here\n")
    rc = cmd_list(_args(config=str(empty)), plain_style)
    assert rc == 0
    assert "No hosts found" in capsys.readouterr().out


def test_cmd_search_matches_hostname(sample_config, plain_style, capsys):
    rc = cmd_search(_args(config=sample_config, term="internal"), plain_style)
    out = capsys.readouterr().out
    assert rc == 0
    assert "db1" in out and "db-primary" in out
    assert "web-prod" not in out


def test_cmd_search_no_match_returns_1(sample_config, plain_style, capsys):
    rc = cmd_search(_args(config=sample_config, term="zzz-nope"), plain_style)
    assert rc == 1
    assert "No hosts matching" in capsys.readouterr().out
