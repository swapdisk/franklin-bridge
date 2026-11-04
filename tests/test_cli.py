"""Tests for CLI helpers and end-to-end wiring (with a fake probe)."""
import pytest

from franklin_bridge import cli
from franklin_bridge.model import MIB, GIB

from .support import load_raw


def test_parse_size_bare_number_is_mib():
    assert cli.parse_size("200") == 200 * MIB


def test_parse_size_suffixes():
    assert cli.parse_size("512M") == 512 * MIB
    assert cli.parse_size("1G") == 1 * GIB
    assert cli.parse_size("200MiB") == 200 * MIB
    assert cli.parse_size("1024k") == 1024 * 1024


def test_parse_size_rejects_garbage():
    with pytest.raises(ValueError):
        cli.parse_size("banana")


class _FakeProbe(object):
    def __init__(self, scenario, **kw):
        self._scenario = scenario
        self._kw = kw

    def collect(self, disk_override=None):
        return load_raw(self._scenario, disk_override=disk_override, **self._kw)


def test_main_healthy_returns_zero(monkeypatch, capsys):
    monkeypatch.setattr(cli, "Probe", lambda: _FakeProbe("rhel8_dos_standard"))
    rc = cli.main(["--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Preflight PASSED" in out
    assert "Conversion plan" in out
    assert "Backup (dry-run preview)" in out


def test_main_apply_without_confirmation_aborts(monkeypatch, capsys):
    # Non-interactive apply (no --yes) must refuse to make changes.
    monkeypatch.setattr(cli, "Probe", lambda: _FakeProbe("rhel8_dos_standard"))
    rc = cli.main([])
    out = capsys.readouterr().out
    assert rc == 1
    assert "Aborted" in out


def test_main_uefi_returns_one(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "Probe", lambda: _FakeProbe("rhel8_dos_standard", efi_present=True)
    )
    rc = cli.main(["--dry-run"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "Preflight FAILED" in out
