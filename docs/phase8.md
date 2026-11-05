# Phase 8 — Validate & Report

> Part of the plan in [`design.md`](design.md) §6. Read-only: re-probes the
> converted system, verifies the hybrid-boot end-state, and prints the final
> operator summary.

## What it checks

Phase 8 re-probes the live system (so it sees the post-conversion GPT layout and
mounted ESP) and verifies every expected artifact:

- disk is **GPT**
- **BIOS Boot** partition present; **EFI System Partition** present
- ESP is **vfat, mounted at /boot/efi**, and **populated** (`grubx64.efi`,
  `shimx64.efi`)
- **UEFI fallback** `EFI/BOOT/BOOTX64.EFI` present
- **bootstrap** `grub.cfg` chains to the real config by the `/boot` UUID
- **real** `grub.cfg` present; **grubenv** is a real file
- `/etc/grub2.cfg` and `/etc/grub2-efi.cfg` point to the real config
- **BIOS GRUB modules** installed; **fstab** has the ESP entry

Each is reported as a pass/fail check. The command exits non-zero if any fail.

## Final summary

On success the tool prints:

- that the disk is now configured for hybrid BIOS/UEFI boot,
- to **reboot** to finalize the new partition table,
- that the system keeps booting in Legacy BIOS mode for now,
- and that switching the firmware to UEFI later needs **no extra steps** — the
  system boots via the EFI fallback and creates its own UEFI boot entry on the
  first UEFI boot.

## Testability

`check_end_state(facts, obs, boot_uuid)` is pure and unit-tested; the live
observations are gathered separately (`gather_end_state`), and the re-probe is
injectable so `execute_validation` can be tested without touching a real system.

## Verified on r8iso

A resume run re-ran the idempotent phases and then reported all 12 end-state
checks passing, with the completion summary.
