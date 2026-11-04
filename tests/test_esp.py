"""Tests for Phase 4 ESP filesystem, migration, and mount."""
from franklin_bridge.esp import (
    ESP_FSTAB_OPTIONS,
    execute_esp,
    fstab_has_mount,
    fstab_line,
    target_esp_device,
)
from franklin_bridge.inventory import build_facts
from franklin_bridge.model import EFI_PACKAGES
from franklin_bridge.plan import build_plan

from .support import FakeExecutor, load_raw, make_facts


def test_fstab_line_format():
    line = fstab_line("ABCD-1234")
    assert line == "UUID=ABCD-1234  /boot/efi  vfat  %s  0 2\n" % ESP_FSTAB_OPTIONS


def test_fstab_has_mount():
    text = (
        "# comment /boot/efi\n"
        "UUID=xxx / xfs defaults 0 0\n"
        "UUID=yyy /boot xfs defaults 0 0\n"
    )
    assert fstab_has_mount(text, "/boot") is True
    assert fstab_has_mount(text, "/boot/efi") is False


def test_target_esp_device_fresh():
    facts = make_facts()
    plan = build_plan(facts)
    # Existing parts are 1 and 2; ESP is created as #4 (after biosboot #3).
    assert target_esp_device(facts, plan) == "/dev/vda4"


def test_target_esp_device_resume_uses_existing():
    facts = build_facts(load_raw("gpt_converted"), EFI_PACKAGES)
    plan = build_plan(facts)
    assert target_esp_device(facts, plan) == facts.existing_esp.device


def test_execute_esp_migrates_existing_content():
    facts = make_facts()
    plan = build_plan(facts)
    fe = FakeExecutor(
        existing={"/boot/efi", "/dev/vda4"},
        dir_entries={"/boot/efi": ["EFI"]},
        files={"/etc/fstab": "UUID=root / xfs defaults 0 0\n"},
        uuid="BEEF-1234",
        mounted=set(),
    )
    summary = execute_esp(fe, facts, plan)

    argvs = [c[1] for c in fe.calls_of("run")]
    assert ("mkfs.vfat", "-F", "32", "/dev/vda4") in argvs
    # Existing content moved aside, then copied back onto the mounted ESP.
    assert ("mv", "/boot/efi", "/boot/efi.franklin-orig") in argvs
    assert ("mount", "/boot/efi") in argvs
    assert ("cp", "-r", "/boot/efi.franklin-orig/.", "/boot/efi/") in argvs
    assert ("rm", "-rf", "/boot/efi.franklin-orig") in argvs

    # fstab entry appended with the real UUID.
    appends = fe.calls_of("append_text")
    assert len(appends) == 1
    assert "UUID=BEEF-1234" in appends[0][2]
    assert "/boot/efi" in appends[0][2]

    # fstab changed -> systemd is reloaded.
    assert ("systemctl", "daemon-reload") in argvs

    assert summary["migrated"] is True
    assert summary["uuid"] == "BEEF-1234"
    assert summary["device"] == "/dev/vda4"


def test_execute_esp_no_existing_content_skips_migration():
    facts = make_facts()
    plan = build_plan(facts)
    fe = FakeExecutor(
        existing={"/boot/efi", "/dev/vda4"},
        dir_entries={"/boot/efi": []},  # empty mount point
        files={"/etc/fstab": ""},
        mounted=set(),
    )
    summary = execute_esp(fe, facts, plan)
    argvs = [c[1] for c in fe.calls_of("run")]
    assert not any(a[0] == "mv" for a in argvs)
    assert not any(a[0] == "cp" for a in argvs)
    assert summary["migrated"] is False


def test_execute_esp_does_not_reformat_existing_fat():
    # ESP exists, is already FAT, but is not mounted (e.g. interrupted run).
    facts = make_facts()
    plan = build_plan(facts)
    fe = FakeExecutor(
        existing={"/boot/efi", "/dev/vda4"},
        dir_entries={"/boot/efi": []},
        files={"/etc/fstab": ""},
        mounted=set(),
        dev_fstype="vfat",
    )
    execute_esp(fe, facts, plan)
    argvs = [c[1] for c in fe.calls_of("run")]
    assert not any(a[0] == "mkfs.vfat" for a in argvs)  # not reformatted
    assert ("mount", "/boot/efi") in argvs               # but still mounted


def test_execute_esp_skips_if_already_mounted():
    facts = make_facts()
    plan = build_plan(facts)
    fe = FakeExecutor(existing={"/dev/vda4"}, mounted={"/boot/efi"})
    summary = execute_esp(fe, facts, plan)
    assert summary["skipped"] is True
    # Nothing was formatted.
    assert not any(c[1][0] == "mkfs.vfat" for c in fe.calls_of("run"))


def test_execute_esp_does_not_duplicate_fstab_entry():
    facts = make_facts()
    plan = build_plan(facts)
    fe = FakeExecutor(
        existing={"/boot/efi", "/dev/vda4"},
        dir_entries={"/boot/efi": []},
        files={"/etc/fstab": "UUID=old /boot/efi vfat umask=0077 0 2\n"},
        mounted=set(),
    )
    execute_esp(fe, facts, plan)
    assert fe.calls_of("append_text") == []  # entry already present
    # fstab unchanged -> no daemon-reload.
    argvs = [c[1] for c in fe.calls_of("run")]
    assert ("systemctl", "daemon-reload") not in argvs


def test_execute_esp_dry_run_previews(tmp_path):
    import os

    from franklin_bridge.executor import Executor

    logs = []
    ex = Executor(dry_run=True, log=logs.append)
    facts = make_facts()
    plan = build_plan(facts)
    # Isolate from the host's real /boot/efi (which may be a live mount here).
    plan.esp_mountpoint = os.path.join(str(tmp_path), "efi")
    summary = execute_esp(ex, facts, plan)
    assert summary["uuid"] == "<esp-uuid>"
    assert any("would run: mkfs.vfat" in m for m in logs)
    assert any("would run: mount " in m for m in logs)
    assert any("would run: systemctl daemon-reload" in m for m in logs)
