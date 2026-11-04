# Phase 4 — ESP Filesystem & Mount

> Part of the plan in [`design.md`](design.md) §6. Formats the EFI System
> Partition, registers it in fstab, and mounts it at `/boot/efi` — migrating any
> existing content onto it rather than burying it.

## The burying problem

On a BIOS-installed RHEL system, `/boot/efi` is a plain directory on the `/boot`
filesystem, and `grub2-common` owns `/boot/efi/EFI/redhat` there (empty). If
`grub2-efi-x64` were ever installed on the BIOS system (unusual, but possible),
its files would live there too. Simply mounting the new ESP at `/boot/efi` would
**hide** all of that — and in the pre-installed case rpm would still think the
package is present, so Phase 5's `dnf install` would be a no-op and the ESP would
end up **empty and unbootable**.

## What it does: migrate, don't bury

1. `mkfs.vfat -F 32` the ESP partition; read its UUID (`blkid`).
2. If `/boot/efi` has any contents, move it aside to `/boot/efi.franklin-orig`.
3. Create a fresh `/boot/efi` mount point; add the fstab entry by UUID
   (`vfat  umask=0077,shortname=winnt  0 2`) if not already present. If fstab was
   changed, run `systemctl daemon-reload` so systemd re-reads it (tolerant of
   non-systemd environments). Then mount it.
4. Copy the preserved contents onto the now-mounted ESP, then remove the aside
   copy.

The format step is skipped if the partition already holds a FAT filesystem
(`blkid`), so a re-run after an interrupted conversion will not wipe a populated
ESP.

This preserves the `grub2-common` directory (and, with `umask=0077`, its 700
mode, keeping `rpm -V` clean) and carries any pre-existing EFI stack onto the ESP.
A matching **Phase 5 safeguard** reinstalls already-installed EFI packages so
their files are guaranteed written to the mounted ESP.

## Idempotent / resumable

If `/boot/efi` is already a mount, Phase 4 is skipped. If the ESP already exists
(from a prior run), its device is reused rather than recomputed from the plan.

## Verified on r8iso

Real run (resuming on the already-GPT disk — Phase 3 correctly did nothing):
formatted vda4 as vfat, added the UUID fstab entry, migrated the
`grub2-common`-owned `EFI/redhat` onto the ESP, removed the aside copy, and the
mount survives `umount` + `mount -a`. `rpm -V grub2-common` (as root) is clean.
