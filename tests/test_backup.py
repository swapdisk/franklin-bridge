"""Tests for Phase 2 backup planning and execution."""
import os

from franklin_bridge.backup import (
    COPY_CANDIDATES,
    MBR_BACKUP_NAME,
    RESTORE_DOC_NAME,
    TABLE_BACKUP_NAME,
    execute_backup,
    flatten_path,
    plan_backup,
)

from .support import FakeExecutor, make_facts


def test_plan_backup_commands_and_disk():
    plan = plan_backup(make_facts(), "/bk/dir")
    assert plan.backup_dir == "/bk/dir"
    assert plan.disk == "/dev/vda"
    # The partition-table dump is first and targets the right disk.
    first_dest, first_argv = plan.commands[0]
    assert first_dest == TABLE_BACKUP_NAME
    assert first_argv == ("sfdisk", "--dump", "/dev/vda")
    dests = [d for d, _ in plan.commands]
    assert "blkid.txt" in dests
    assert plan.copy_candidates == COPY_CANDIDATES


def test_restore_doc_mentions_disk_and_restore_commands():
    plan = plan_backup(make_facts(), "/bk/dir")
    doc = plan.restore_doc
    assert "/dev/vda" in doc
    assert "sfdisk /dev/vda" in doc
    assert TABLE_BACKUP_NAME in doc
    assert MBR_BACKUP_NAME in doc


def test_flatten_path():
    assert flatten_path("/etc/fstab") == "etc_fstab"
    assert flatten_path("/boot/grub2/grubenv") == "boot_grub2_grubenv"


def test_execute_backup_records_expected_actions():
    fe = FakeExecutor(existing={"/etc/fstab", "/boot/grub2/grub.cfg"})
    summary = execute_backup(fe, plan_backup(make_facts(), "/bk"))

    # Directory created first.
    assert ("makedirs", "/bk") in fe.calls

    # Each capture command writes to a file under the backup dir.
    runs = fe.calls_of("run")
    table_runs = [c for c in runs
                  if c[2] == os.path.join("/bk", TABLE_BACKUP_NAME)]
    assert len(table_runs) == 1
    assert table_runs[0][1] == ("sfdisk", "--dump", "/dev/vda")

    # The raw disk-head dd happened.
    dd_runs = [c for c in runs if c[1] and c[1][0] == "dd"]
    assert len(dd_runs) == 1
    assert "of=%s" % os.path.join("/bk", MBR_BACKUP_NAME) in dd_runs[0][1]

    # Only existing files were copied; the rest skipped.
    assert set(summary["copied"]) == {"/etc/fstab", "/boot/grub2/grub.cfg"}
    assert "/etc/grub2.cfg" in summary["skipped"]

    # The restore doc was written.
    writes = [c for c in fe.calls_of("write_text")
              if c[1] == os.path.join("/bk", RESTORE_DOC_NAME)]
    assert len(writes) == 1


def test_execute_backup_dry_run_writes_nothing(tmp_path):
    from franklin_bridge.executor import Executor

    target = os.path.join(str(tmp_path), "backup-test")
    logs = []
    ex = Executor(dry_run=True, log=logs.append)
    execute_backup(ex, plan_backup(make_facts(), target))

    # Nothing was actually created on disk.
    assert not os.path.exists(target)
    # But the intended actions were logged.
    assert any("would create directory" in m for m in logs)
    assert any("would run" in m for m in logs)
