# Phase 5 — EFI Stack Population

> Part of the plan in [`design.md`](design.md) §6. Installs the EFI bootloader
> onto the (now-mounted) ESP and ensures the UEFI fallback path is in place.
> Runs after Phase 4 so the packages' files land on the ESP, not under it.

## What it does

1. **Install** `shim-x64` + `grub2-efi-x64` if missing; ensure `grub2-pc` is
   present (needed for the Phase 6 BIOS GRUB reinstall).
2. **Reinstall** any EFI-on-ESP package (`shim-x64`, `grub2-efi-x64`) that was
   *already* installed, so its files are rewritten onto the ESP we just mounted.
   (A package installed while `/boot/efi` was still a plain directory would
   otherwise have its files hidden under the mount — the bumbling-sysadmin case.)
3. **Verify** the ESP is populated (`grubx64.efi`, `shimx64.efi` present).
4. **Ensure the UEFI fallback** `\EFI\BOOT\BOOTX64.EFI` exists — only creating it
   if absent (see below).

No `efibootmgr` / EFI `grub2-install`: we are booted in BIOS mode, so UEFI NVRAM
is not writable. The fallback path is what lets a later firmware switch to UEFI
boot with no NVRAM entry present.

## The fallback is usually provided by the package

Confirmed on RHEL 8.10 (`shim-x64-16.1`): the package itself installs the whole
fallback onto the mounted ESP —

- `/boot/efi/EFI/BOOT/BOOTX64.EFI` (shim)  — owned by `shim-x64`
- `/boot/efi/EFI/BOOT/fbx64.efi`           — owned by `shim-x64`
- `/boot/efi/EFI/redhat/BOOTX64.CSV`       — owned by `shim-x64`

So `_ensure_fallback` normally finds `BOOTX64.EFI` already present and leaves it.
Its create-from-shim branch is a **safety net** for cases where the files are
missing from the ESP (e.g. packages pre-installed before the ESP existed, or an
otherwise stripped setup).

## Idempotent / resumable

Re-running is safe: `dnf install` of an installed package is a no-op, `reinstall`
simply rewrites files, and the fallback is left alone when already present.

## Verified on r8iso

Real run installed `shim-x64` + `grub2-efi-x64` onto the mounted ESP, populated
`/boot/efi/EFI/redhat`, and the package-provided `\EFI\BOOT` fallback was detected
and left in place.
