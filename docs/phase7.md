# Phase 7 — Unified GRUB2 Configuration

> Part of the plan in [`design.md`](design.md) §6; implements KB 6718341 §3.
> Produces the one configuration that boots identically under BIOS and UEFI.

## Target layout

- `/boot/grub2/grub.cfg` — the **real** config (`grub2-mkconfig`)
- `/boot/grub2/grubenv` — a **real file** (not a symlink to the ESP)
- `/boot/efi/EFI/redhat/grub.cfg` — a **bootstrap** config that finds `/boot` by
  filesystem UUID and chains to the real config
- `/etc/grub2.cfg`, `/etc/grub2-efi.cfg` → `../boot/grub2/grub.cfg`

## Steps

1. **Ensure `grubenv` is a real file.** On a BIOS-origin system it already is;
   if it were a symlink (UEFI-origin), replace it with `grub2-editenv create`.
2. **Generate the real config:** `grub2-mkconfig -o /boot/grub2/grub.cfg`.
3. **Write the bootstrap config** (KB §3.1 item 4). The `/boot` filesystem UUID
   comes from `grub2-probe --target=fs_uuid /boot/grub2` and the in-filesystem
   path from `grub2-mkrelpath /boot/grub2`:

   ```
   connectefi scsi
   search --no-floppy --fs-uuid --set=dev <boot-uuid>
   set prefix=($dev)/grub2
   export $prefix
   configfile $prefix/grub.cfg
   ```
4. **Point both `/etc` symlinks** at the real config (idempotent: an
   already-correct link is left alone; a mispointed one is removed and recreated).
5. **Remove `grubenv.rpmnew`** if a package left one behind.

## How both firmwares converge

- **UEFI:** shim → `grubx64.efi` reads the bootstrap `grub.cfg`, does a
  `search --fs-uuid` for `/boot`, then `configfile`s the real config.
- **BIOS:** `core.img` reads `/boot/grub2/grub.cfg` directly.

Both execute the same real `/boot/grub2/grub.cfg`.

## Verified on r8iso

Real run left the already-real `grubenv` alone, regenerated the real config
(198 lines, 4 menuentries), wrote the bootstrap config with the correct `/boot`
UUID (`b1d0fe98-…`) and `/grub2` prefix, left the already-correct `/etc/grub2.cfg`
link untouched, and repointed `/etc/grub2-efi.cfg` (which the grub2-efi-x64
install had aimed at the EFI path) to the real config — exactly the KB §3.3 fix.
