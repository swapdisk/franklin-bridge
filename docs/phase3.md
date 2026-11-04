# Phase 3 — Partition Surgery (destructive)

> Part of the plan in [`design.md`](design.md) §6. This is the first phase that
> writes to the disk. It runs only after the Phase 2 backup, behind the
> confirmation guard, and every step honors `--dry-run`.

## What it does

On the primary disk (which already has free space at the end):

1. **Convert DOS → GPT** in place: `sgdisk -g <disk>`. Existing partitions keep
   their exact start sectors and sizes; their type codes map over (83→8300,
   8e→8e00). Filesystems and data are untouched.
2. **Create the BIOS Boot partition** (type `ef02`, 1 MiB) and the **EFI System
   Partition** (type `ef00`, `--esp-size`, default 200 MiB). Both are placed by
   `sgdisk` in the largest free block (the space at the end of the disk).
3. **Register the new partitions** with the kernel via `partx -a --nr <n>`.

Partition numbers are computed from the existing table (new ones follow the
highest existing number). After a run the tool verifies the new partition device
nodes actually appeared, and raises if not.

## Important: bootability during the conversion

`sgdisk -g` writes the GPT headers into sectors 1–33, which **overwrites the
post-MBR gap where the current BIOS GRUB core image lives**. Therefore, between
Phase 3 and Phase 6 (GRUB reinstall) the system is **not reboot-safe** — the
running system stays up and usable, but a reboot before Phase 6 would fail to
boot. The required reboot only happens after the whole conversion completes.

## Idempotent / resumable

If the disk is already GPT, the conversion step is skipped; if a BIOS Boot or EFI
System partition already exists, its creation is skipped. So re-running the tool
on a partially-converted disk simply continues from where it left off.

## Live-disk note

Because the existing partitions are mounted, the kernel will not re-read the full
table. Only the new partitions are added (`partx -a`); existing partitions keep
their sectors, so the kernel's view stays consistent until the final reboot.

## Verified on r8iso

Real run converted the disk to GPT (`sgdisk -v`: no problems), preserved vda1
(/boot) and vda2 (LVM) at identical sectors, created vda3 (EF02) and vda4 (EF00,
200 MiB) in the end free space, kept all mounts, and left the `/boot` filesystem
UUID unchanged.
