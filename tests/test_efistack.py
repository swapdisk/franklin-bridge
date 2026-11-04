"""Tests for Phase 5 EFI stack population."""
import pytest

from franklin_bridge.efistack import (
    execute_efistack,
    plan_efi_packages,
)
from franklin_bridge.plan import build_plan

from .support import FakeExecutor, make_facts

ESP_FILES = {"/boot/efi/EFI/redhat/grubx64.efi", "/boot/efi/EFI/redhat/shimx64.efi"}


def test_plan_fresh_bios_system_installs_efi_packages():
    # Default make_facts: nothing EFI installed, grub2-pc installed.
    facts = make_facts()
    to_install, to_reinstall = plan_efi_packages(facts)
    assert set(to_install) == {"shim-x64", "grub2-efi-x64"}
    assert to_reinstall == []


def test_plan_reinstalls_already_installed_efi_packages():
    facts = make_facts(packages={
        "shim-x64": True, "grub2-efi-x64": True, "grub2-pc": True})
    to_install, to_reinstall = plan_efi_packages(facts)
    assert to_install == []
    assert set(to_reinstall) == {"shim-x64", "grub2-efi-x64"}


def test_plan_installs_missing_grub2_pc():
    facts = make_facts(packages={
        "shim-x64": False, "grub2-efi-x64": False, "grub2-pc": False})
    to_install, _ = plan_efi_packages(facts)
    assert "grub2-pc" in to_install


def test_execute_installs_and_creates_fallback_when_absent():
    facts = make_facts()
    plan = build_plan(facts)
    # ESP binaries present (install "succeeded"); fallback dir absent, fbx64 present.
    fe = FakeExecutor(existing=ESP_FILES | {"/boot/efi/EFI/redhat/fbx64.efi"})
    summary = execute_efistack(fe, facts, plan)

    argvs = [c[1] for c in fe.calls_of("run")]
    assert ("dnf", "-y", "install", "shim-x64", "grub2-efi-x64") in argvs
    assert not any(a[:3] == ("dnf", "-y", "reinstall") for a in argvs)

    # Fallback created from shim, plus the fallback binary copied.
    copies = fe.calls_of("copy")
    assert ("/boot/efi/EFI/redhat/shimx64.efi",
            "/boot/efi/EFI/BOOT/BOOTX64.EFI") in [(c[1], c[2]) for c in copies]
    assert ("/boot/efi/EFI/redhat/fbx64.efi",
            "/boot/efi/EFI/BOOT/fbx64.efi") in [(c[1], c[2]) for c in copies]
    assert summary["fallback_created"] is True


def test_execute_leaves_fallback_if_package_provided_it():
    facts = make_facts()
    plan = build_plan(facts)
    # The package already dropped BOOTX64.EFI into \EFI\BOOT.
    fe = FakeExecutor(existing=ESP_FILES | {"/boot/efi/EFI/BOOT/BOOTX64.EFI"})
    summary = execute_efistack(fe, facts, plan)
    assert summary["fallback_created"] is False
    assert fe.calls_of("copy") == []  # nothing to set up


def test_execute_reinstalls_when_already_installed():
    facts = make_facts(packages={
        "shim-x64": True, "grub2-efi-x64": True, "grub2-pc": True})
    plan = build_plan(facts)
    fe = FakeExecutor(existing=ESP_FILES | {"/boot/efi/EFI/BOOT/BOOTX64.EFI"})
    execute_efistack(fe, facts, plan)
    argvs = [c[1] for c in fe.calls_of("run")]
    assert ("dnf", "-y", "reinstall", "shim-x64", "grub2-efi-x64") in argvs


def test_execute_raises_if_esp_not_populated():
    facts = make_facts()
    plan = build_plan(facts)
    fe = FakeExecutor(existing=set())  # install "ran" but ESP has no binaries
    with pytest.raises(RuntimeError):
        execute_efistack(fe, facts, plan)


def test_execute_dry_run_skips_verify_and_previews():
    from franklin_bridge.executor import Executor

    logs = []
    ex = Executor(dry_run=True, log=logs.append)
    facts = make_facts()
    plan = build_plan(facts)
    summary = execute_efistack(ex, facts, plan)  # must not raise despite empty ESP
    assert any("would run: dnf -y install" in m for m in logs)
    assert summary["installed"]
