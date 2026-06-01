"""Shared fixtures for the sshko test suite."""

import textwrap

import pytest

from sshko.cli import Style


@pytest.fixture
def plain_style():
    """A Style with coloring disabled, so assertions match raw text."""
    return Style(enabled=False)


@pytest.fixture
def sample_config(tmp_path):
    """Write a representative config (wildcards, negation, includes) and return its path."""
    conf_d = tmp_path / "conf.d"
    conf_d.mkdir()

    (tmp_path / "config").write_text(textwrap.dedent("""\
        # global defaults
        Host *
            ForwardAgent yes
            ServerAliveInterval 60

        Host web-prod
            HostName 10.0.0.5
            User deploy
            Port 2222

        Host web-* !web-old
            User www-data
            IdentityFile ~/.ssh/web_key

        Include conf.d/*.conf
    """))

    (conf_d / "extra.conf").write_text(textwrap.dedent("""\
        Host db1 db-primary
            HostName db1.internal
            User postgres
    """))

    return str(tmp_path / "config")
