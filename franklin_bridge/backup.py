"""Phase 2 - Backup & safety net.

Split into a pure planner (plan_backup) and an impure executor-driven runner
(execute_backup). The planner decides *what* to capture; the runner performs it
through an Executor so it honors dry-run and is testable with a fake executor.
"""
import os
from typing import NamedTuple, Tuple

from .model import MIB

LSBLK_COLUMNS = "NAME,TYPE,SIZE,FSTYPE,UUID,PARTTYPE,MOUNTPOINT,PKNAME"

# First this many bytes of the disk are saved raw: the MBR boot code, the
# partition table, and the post-MBR gap where BIOS GRUB's core image lives.
DISK_HEAD_BYTES = 1 * MIB

MBR_BACKUP_NAME = "disk-first-1MiB.bin"
TABLE_BACKUP_NAME = "partition-table.sfdisk"
RESTORE_DOC_NAME = "RESTORE.md"

# Files copied verbatim if they exist (bootloader config + fstab).
COPY_CANDIDATES = (
    "/etc/fstab",
    "/etc/default/grub",
    "/etc/grub2.cfg",
    "/etc/grub2-efi.cfg",
    "/boot/grub2/grub.cfg",
    "/boot/grub2/grubenv",
)


class BackupPlan(NamedTuple):
    backup_dir: str
    disk: str
    commands: Tuple[Tuple[str, Tuple[str, ...]], ...]  # (dest_filename, argv)
    head_bytes: int
    copy_candidates: Tuple[str, ...]
    restore_doc: str


def plan_backup(facts, backup_dir):
    """Decide what to back up (pure)."""
    disk = facts.disk.path
    commands = (
        (TABLE_BACKUP_NAME, ("sfdisk", "--dump", disk)),
        ("lsblk.json", ("lsblk", "-J", "-b", "-o", LSBLK_COLUMNS)),
        ("findmnt.json", ("findmnt", "-J", "-o", "TARGET,SOURCE")),
        ("parted-print-free.txt",
         ("parted", "-m", "-s", disk, "unit", "s", "print", "free")),
        ("blkid.txt", ("blkid",)),
    )
    return BackupPlan(
        backup_dir=backup_dir,
        disk=disk,
        commands=commands,
        head_bytes=DISK_HEAD_BYTES,
        copy_candidates=COPY_CANDIDATES,
        restore_doc=_restore_doc(disk, backup_dir),
    )


def flatten_path(path):
    """/etc/fstab -> etc_fstab (avoid nested dirs inside the backup)."""
    return path.strip("/").replace("/", "_")


def execute_backup(executor, plan):
    """Perform the backup through the executor. Returns a summary dict."""
    executor.makedirs(plan.backup_dir)

    captured = []
    for dest, argv in plan.commands:
        out_path = os.path.join(plan.backup_dir, dest)
        executor.run(list(argv), mutates=True, capture_to=out_path)
        captured.append(dest)

    mbr_path = os.path.join(plan.backup_dir, MBR_BACKUP_NAME)
    count = plan.head_bytes // 512
    executor.run(
        ["dd", "if=%s" % plan.disk, "of=%s" % mbr_path, "bs=512",
         "count=%d" % count, "conv=notrunc", "status=none"],
        mutates=True,
    )
    captured.append(MBR_BACKUP_NAME)

    copied = []
    skipped = []
    for src in plan.copy_candidates:
        if executor.exists(src):
            dest = os.path.join(plan.backup_dir, flatten_path(src))
            executor.copy(src, dest)
            copied.append(src)
        else:
            skipped.append(src)

    executor.write_text(
        os.path.join(plan.backup_dir, RESTORE_DOC_NAME), plan.restore_doc
    )

    return {
        "backup_dir": plan.backup_dir,
        "captured": captured,
        "copied": copied,
        "skipped": skipped,
    }


def _restore_doc(disk, backup_dir):
    return (
        "# Franklin Bridge - backup & restore notes\n"
        "\n"
        "Backup of %s taken before converting it to hybrid BIOS/UEFI boot.\n"
        "\n"
        "## Contents\n"
        "\n"
        "- `%s` - partition table dump (restore with sfdisk)\n"
        "- `%s` - first 1 MiB of the disk: MBR boot code, partition table,\n"
        "  and the post-MBR gap containing the BIOS GRUB core image\n"
        "- `etc_fstab`, `etc_default_grub`, `*grub*.cfg`, `boot_grub2_grubenv`\n"
        "  - copies of the bootloader configuration and fstab\n"
        "- `lsblk.json`, `findmnt.json`, `parted-print-free.txt`, `blkid.txt`\n"
        "  - the pre-conversion system state, for reference\n"
        "\n"
        "## Restoring (boot from rescue media first)\n"
        "\n"
        "Restore the partition table:\n"
        "\n"
        "    sfdisk %s < %s\n"
        "\n"
        "Or restore the MBR + partition table + GRUB core image wholesale:\n"
        "\n"
        "    dd if=%s of=%s bs=512 conv=notrunc\n"
        "\n"
        "Then restore any needed config files by copying them back to their\n"
        "original locations (see the file names above).\n"
        % (
            disk,
            TABLE_BACKUP_NAME,
            MBR_BACKUP_NAME,
            disk, os.path.join(backup_dir, TABLE_BACKUP_NAME),
            os.path.join(backup_dir, MBR_BACKUP_NAME), disk,
        )
    )
