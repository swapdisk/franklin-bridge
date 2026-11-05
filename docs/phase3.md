# Phase 3 - Partition Surgery (destructive)

> Part of the plan in [`design.md`](design.md) §6. This is the first phase that
> writes to the disk. It runs only after the Phase 2 backup, behind the
> confirmation guard, and every step honors `--dry-run`.

Partitioning uses **`sfdisk`** (util-linux). It does **not** depend on
`gdisk`/`sgdisk`, which is not shipped on RHEL 10.

## What it does

On the primary disk (which already has free space at the end):

1. **Convert DOS to GPT** by reading the current layout with `sfdisk -d`,
   rewriting it as a GPT script that preserves each existing partition at its
   exact start/size (translating MBR type bytes to GPT type GUIDs) and adds the
   two new partitions, then applying it with `sfdisk --no-reread`.
2. The new partitions are the **BIOS Boot** partition (type `21686148-...`,
   1 MiB) and the **EFI System Partition** (type `C12A7328-...`, `--esp-size`,
   default 200 MiB), placed by sfdisk in the free space after the last existing
   partition.
3. **Register the new partitions** with the kernel via `partx -a --nr <n>`.

On an already-GPT disk (resume), the conversion is skipped and any missing
partition is added with `sfdisk --append`, touching nothing else.

## Safety

- **Preflight refuses what we can't safely convert** (see
  [phase1.md](phase1.md)): extended/logical partitions, or any MBR partition
  type outside the known-safe set (Linux `83`, LVM `8e`, swap `82`). So the
  rewrite only ever runs on a small set of known primary partitions whose exact
  geometry we read off the disk.
- **Post-write verification:** after applying, the tool confirms the new device
  nodes appeared and that every preserved partition kept its exact start/size.
  On any mismatch it raises, and the Phase 2 backup (`sfdisk --dump` plus the
  first-MiB `dd`) can restore the original table.

## Important: bootability during the conversion

Writing the GPT overwrites the post-MBR gap where the current BIOS GRUB core
image lives. Therefore, between Phase 3 and Phase 6 (GRUB reinstall) the system
is **not reboot-safe**: the running system stays up and usable, but a reboot
before Phase 6 would fail to boot. The required reboot only happens after the
whole conversion completes.

## Idempotent / resumable

If the disk is already GPT, the conversion step is skipped; if a BIOS Boot or EFI
System partition already exists, its creation is skipped. Re-running continues
from where it left off.

## Live-disk note

Because existing partitions are mounted, the kernel will not re-read the full
table. Only the new partitions are added (`partx -a`); existing partitions keep
their sectors, so the kernel's view stays consistent until the final reboot.

## Verified on test VMs

Full conversions validated on RHEL 8 (plain LVM and LVM thin pool) and the
RHEL 9 verify/repair path, each followed by a clean reboot.
