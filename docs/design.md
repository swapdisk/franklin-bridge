# Franklin Bridge: Design

## 1. Purpose

Convert a **running RHEL system currently booting in Legacy BIOS mode** (DOS/MBR
partition table, no EFI System Partition) into a **hybrid-boot** configuration,
that is, one that boots correctly whether the firmware is later set to **Legacy
BIOS** or **UEFI**, following the unified GRUB2 layout recommended in §3 of the
Red Hat knowledge article [How to configure Grub2 to be able to boot
alternatively on UEFI or BIOS mode](https://access.redhat.com/articles/6718341)
(KB 6718341).

The firmware switch itself is **out of scope** by design: the hybrid layout
decouples the OS-side automation from the firmware-mode change, which an
organization can perform later, manually or via API, at its convenience.

### Why this is more than the KB article

KB 6718341 §3.3 ("Fix on BIOS mode systems") assumes two prerequisites are
**already done**:

1. the disk already uses a **GPT** partition table, and
2. a populated, mounted **`/boot/efi`** ESP already exists.

Franklin Bridge's main value-add is **automating those skipped prerequisites**
(DOS→GPT conversion, BIOS Boot partition, ESP creation/format/mount, shim +
`grub2-efi` population), and *then* performing the KB 6718341 §3.3
unified-config steps.

## 2. Settled decisions

| Decision | Choice |
| --- | --- |
| Language | **Python, stdlib-only**, target **3.6 → 3.12** (no 2.7 straddle, no third-party deps) |
| Version scope | **RHEL 8, 9, 10** |
| Execution model | **Live running system first** (grow VM disk → run → reboot) |
| RPM packaging | Out of scope for now |
| Firmware mode switch | Out of scope (done later by the operator) |
| Architecture | **x86_64** first (aarch64 a possible later extension) |

### Version nuance

RHEL **9 and 10** already ship the unified GRUB2 config by default, so there the
tool's real work is the **partition prerequisites** plus **verify/repair** of
the config. RHEL **8** needs the full KB 6718341 §3.3 config steps. This is
handled by **runtime detection of the current state**, not hardcoded per-version
branches.

## 3. Scope

**In scope**

- DOS → GPT conversion in place (`sfdisk`; no `gdisk`/`sgdisk` dependency)
- Create 1 MB **BIOS Boot** partition (`ef02`) + **EFI System Partition**
  (`ef00`, FAT32, `/boot/efi`), **default 200 MB**, overridable via a
  command-line option (e.g. `--esp-size`)
- Install/populate shim + `grub2-efi-x64`; reinstall BIOS GRUB
  (`grub2-install --target i386-pc`) so `core.img` lands in the new BIOS Boot
  partition
- Implement the unified GRUB2 config: bootstrap `grub.cfg` on the ESP, real
  config in `/boot/grub2`, `grubenv` as a real file, `/etc/grub2*.cfg` symlinks
- **Beyond the article:** populate the UEFI **fallback path**
  `\EFI\BOOT\BOOTX64.EFI` so the system boots after a firmware flip *without*
  needing `efibootmgr` (which cannot run while booted in BIOS mode)
- Safety: preflight checks, backups, `--dry-run`, idempotency, clear reporting

**Out of scope**

- Switching firmware boot mode
- Growing the disk (operator grows the virtual disk first; we require free space)
- Non-x86_64 architectures (for now)

## 4. Assumptions / preconditions (enforced in preflight)

- Running as **root**, and the system is **currently BIOS-booted**
  (`/sys/firmware/efi` absent).
- The primary disk has a **DOS** partition table with **unpartitioned free
  space**, enough for the BIOS Boot + ESP partitions, plus slack at the end of
  the disk for the secondary GPT header/table. (Operator grew the disk first.)
- Standard RHEL layout: a separate `/boot` partition; root on LVM. We do **not**
  move or resize existing partitions.
- Required tools available: `sfdisk`/`parted` (util-linux), `dosfstools`
  (`mkfs.vfat`), `grub2-*`, and reachable dnf repositories for package installs.

## 5. Target end-state (x86_64)

```
GPT disk:
  ├─ /boot                 (unchanged)
  ├─ LVM PV                (unchanged: root + swap)
  ├─ BIOS Boot partition   (~1 MB,   type ef02, no filesystem)
  └─ EFI System Partition  (~200 MB, type ef00, FAT32, mounted /boot/efi)

/boot/grub2/grub.cfg           <- REAL config
/boot/grub2/grubenv            <- real file (not a symlink)
/boot/efi/EFI/redhat/grub.cfg  <- bootstrap (connectefi + configfile → real)
/boot/efi/EFI/BOOT/BOOTX64.EFI <- shim fallback (firmware flip w/o NVRAM entry)
/etc/grub2.cfg, /etc/grub2-efi.cfg -> ../boot/grub2/grub.cfg
```

Bootstrap `/boot/efi/EFI/redhat/grub.cfg` (generated, per KB 6718341 §3.1 item 4):

```
connectefi scsi
search --no-floppy --fs-uuid --set=dev <BOOT_UUID>
set prefix=($dev)<GRUB_DIR>
export $prefix
configfile $prefix/grub.cfg
```

## 6. Building blocks (phased WBS)

Each phase is independently testable and ordered so a failure leaves a
recoverable state. Phases run top-to-bottom; each is idempotent and re-checks
whether its end-state already holds.

1. [**Preflight & inventory**](phase1.md): detect boot mode, primary disk,
   partition table type, filesystem/LVM layout, free space, and required tools.
   Compute the partition plan (sizes, order, free-space placement). Refuse to
   proceed on any unmet precondition with an actionable message.
2. [**Backup & safety net**](phase2.md): save the partition table
   (`sfdisk --dump`), `/etc/fstab`, and existing GRUB configs to a timestamped
   backup dir; record a rollback note.
3. [**Partition surgery**](phase3.md): convert DOS→GPT with `sfdisk` (preserving
   existing partitions); create the BIOS Boot and EFI System partitions in free
   space; register new partitions with the kernel (`partx -a`), noting that full
   table re-read is deferred to reboot.
4. [**ESP filesystem & mount**](phase4.md): `mkfs.vfat -F32` on the ESP; create
   `/boot/efi`; add an fstab entry by UUID; mount it.
5. [**EFI stack population**](phase5.md): install `shim-x64` + `grub2-efi-x64`
   (ensure `grub2-pc` present); verify `/boot/efi/EFI/redhat` is populated; set up
   the `\EFI\BOOT` fallback (`BOOTX64.EFI`, `fbx64.efi`).
6. [**BIOS GRUB reinstall**](phase6.md): `grub2-install --target i386-pc <disk>`
   (now succeeds because the BIOS Boot partition exists).
7. [**Unified GRUB2 config**](phase7.md): write the bootstrap `grub.cfg` on the
   ESP; ensure `grubenv` is a real file in `/boot/grub2`; fix `/etc/grub2*.cfg`
   symlinks; `grub2-mkconfig -o /boot/grub2/grub.cfg`.
8. [**Validate & report**](phase8.md): verify layout, configs, and bootability
   signals; print a summary, a recommendation to reboot to confirm a clean boot
   (not strictly required), and how to later flip the firmware to UEFI.

## 7. Architecture (code structure)

- **Pure logic, unit-tested:** parsing `lsblk`/`sfdisk`/`parted`/`findmnt` output,
  computing the partition plan, rendering config files (bootstrap `grub.cfg`,
  fstab line). No side effects.
- **Execution layer:** a thin wrapper around `subprocess` for all
  state-changing commands, honoring `--dry-run` and centralizing logging. Living
  behind this boundary is what will let a future **rescue-media** mode slot in
  without rewriting the logic.
- **Orchestrator:** runs phases 1-8, each guarded by an idempotency check.

## 8. Cross-cutting concerns

- **`--dry-run`** prints every action without mutating anything.
- **Idempotency:** safe to re-run after a partial failure; each phase detects an
  already-satisfied end-state and skips.
- **Live-disk caveat:** existing partitions cannot be re-read while mounted; the
  tool states this and requires a reboot to finalize.
- **Logging & reporting:** structured, human-readable progress; a final summary
  with next steps.

## 9. Testing strategy

- **Unit tests (in this repo)** for all pure logic (parsers, planner, config
  renderers) across Python 3.6-3.12. These are hermetic (no VM, no RHEL
  content, runnable anywhere) and are the primary feedback loop.
- **Full dual-firmware acceptance:** the real proof is that a converted disk
  boots under both legacy BIOS and UEFI firmware. This requires real-world RHEL
  instances running on your organization's actual infrastructure, be that bare
  metal or virtual, KVM or VMware, etc.

## 10. Open questions / future work

- ~~ESP size default~~ (**resolved**): default 200 MB, overridable via
  `--esp-size`.
- aarch64 support.
- Rescue-media execution mode.
- RPM packaging.
