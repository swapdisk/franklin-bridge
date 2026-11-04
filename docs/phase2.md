# Phase 2 — Backup & Safety Net

> Part of the plan in [`design.md`](design.md) §6. Phase 2 captures everything
> needed to recover the original boot setup before any destructive change. It is
> non-destructive: it only reads the system and writes backup files.

## What gets captured

Into a timestamped directory (default `/var/lib/franklin-bridge/backup-<UTC>`,
parent overridable with `--backup-dir`):

- **`partition-table.sfdisk`** — `sfdisk --dump <disk>`, restorable with
  `sfdisk <disk> < file`.
- **`disk-first-1MiB.bin`** — the first 1 MiB of the disk (MBR boot code, the
  partition table, and the post-MBR gap holding the BIOS GRUB core image).
- **Config copies** (only if present): `/etc/fstab`, `/etc/default/grub`,
  `/etc/grub2.cfg`, `/etc/grub2-efi.cfg`, `/boot/grub2/grub.cfg`,
  `/boot/grub2/grubenv`. Symlinks are followed so the real content is saved;
  `grubenv` is preserved byte-exact (1024 bytes).
- **Reference state**: `lsblk.json`, `findmnt.json`, `parted-print-free.txt`,
  `blkid.txt`.
- **`RESTORE.md`** — human-readable restore instructions.

## Conventions established here (reused by later phases)

- **Execution layer (`executor.py`).** Every mutation — running a command,
  `makedirs`, `write_text`, `copy` — goes through an `Executor`. With
  `dry_run=True` mutations are logged, not performed; read-only helpers
  (`exists`, `islink`) always reflect reality. This is the seam the destructive
  phases (3+) use to stay previewable and testable.
- **Pure planner / impure runner split.** `plan_backup(facts, dir)` is pure and
  unit-tested; `execute_backup(executor, plan)` drives the executor and is tested
  with a fake executor that records actions.
- **Confirmation guard.** Apply mode (no `--dry-run`) requires confirmation;
  non-interactive runs must pass `--yes`, or the tool aborts without changes.

## CLI flow

1. Preflight + plan + validate (Phase 1), always printed.
2. Validation fails → exit 1.
3. `--dry-run` → also preview the backup actions, then stop.
4. Apply → confirm (or `--yes`) → run the safety backup. (Phases 3–8 not yet
   implemented, so nothing touches the disk.)
