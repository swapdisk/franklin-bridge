"""Tests for Phase 6 BIOS GRUB reinstall."""
import pytest

from franklin_bridge.biosgrub import execute_bios_grub, grub2_install_command
from franklin_bridge.plan import build_plan

from .support import FakeExecutor, make_facts

MODULES = {"/boot/grub2/i386-pc/normal.mod"}


def test_grub2_install_command():
    assert grub2_install_command(make_facts()) == [
        "grub2-install", "--target", "i386-pc", "/dev/vda"]


def test_execute_runs_grub2_install_and_verifies():
    facts = make_facts()
    plan = build_plan(facts)
    fe = FakeExecutor(existing=MODULES)
    summary = execute_bios_grub(fe, facts, plan)
    argvs = [c[1] for c in fe.calls_of("run")]
    assert ("grub2-install", "--target", "i386-pc", "/dev/vda") in argvs
    assert summary["skipped"] is False


def test_execute_skips_when_not_needed():
    facts = make_facts()
    plan = build_plan(facts)
    plan.needs_bios_grub_reinstall = False
    fe = FakeExecutor(existing=MODULES)
    summary = execute_bios_grub(fe, facts, plan)
    assert summary["skipped"] is True
    assert fe.calls_of("run") == []


def test_execute_raises_if_modules_missing():
    facts = make_facts()
    plan = build_plan(facts)
    fe = FakeExecutor(existing=set())  # grub2-install "ran" but no modules
    with pytest.raises(RuntimeError):
        execute_bios_grub(fe, facts, plan)


def test_execute_dry_run_skips_verify():
    from franklin_bridge.executor import Executor

    logs = []
    ex = Executor(dry_run=True, log=logs.append)
    facts = make_facts()
    plan = build_plan(facts)
    execute_bios_grub(ex, facts, plan)  # must not raise despite no modules
    assert any("would run: grub2-install --target i386-pc /dev/vda" in m
               for m in logs)
