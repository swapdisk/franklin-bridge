# Phase 6 — BIOS GRUB Reinstall

> Part of the plan in [`design.md`](design.md) §6. Restores Legacy BIOS boot
> after the Phase 3 GPT conversion.

## What it does

    grub2-install --target i386-pc <disk>

This writes GRUB's `boot.img` to the protective MBR boot-code area and embeds
`core.img` into the **BIOS Boot partition** (`ef02`, created in Phase 3). It then
verifies the i386-pc modules are present under `/boot/grub2/i386-pc/`.

## Why it matters

Phase 3's `sgdisk -g` wrote the GPT headers into sectors 1–33, overwriting the
post-MBR gap where the original BIOS `core.img` lived — leaving the system
**not reboot-safe**. Phase 6 reinstalls that core image, now into the dedicated
BIOS Boot partition (which is where GRUB puts it on GPT disks). After this phase
the system can boot in BIOS mode again.

At this point `core.img` chains to the existing `/boot/grub2/grub.cfg` (still the
original, UUID-based config). Phase 7 regenerates that config for the unified
BIOS/UEFI layout.

## Idempotent

`grub2-install` is safe to re-run, so this phase needs no special guard.

## Verified on r8iso

Real run completed with no error; afterward `/boot/grub2/i386-pc/` held 284
modules (incl. `normal.mod`), the protective MBR contained the `GRUB` boot code,
and the BIOS Boot partition (`vda3`) contained the embedded core image (boot
code, not zeros).
