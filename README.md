# Franklin Bridge

Franklin Bridge converts a running Red Hat Enterprise Linux system that boots in
**Legacy BIOS** mode into a **hybrid-boot** configuration, one that boots
correctly whether the firmware is later set to Legacy BIOS *or* UEFI. You can
prepare a fleet for UEFI now and flip each machine's firmware whenever it's
convenient, with no further changes to the OS.

It automates the prerequisites that the manual procedure in Red Hat knowledge
article [How to configure Grub2 to be able to boot alternatively on UEFI or BIOS
mode](https://access.redhat.com/articles/6718341) assumes you have already done
(converting the DOS/MBR disk to GPT, adding a BIOS Boot partition and an EFI
System Partition, and populating the EFI bootloader), and then applies the
unified GRUB2 configuration so both firmware modes boot the same system.

## Why hybrid boot?

Migrating from BIOS to UEFI normally couples two hard things: reconfiguring the
OS *and* switching the firmware mode (which may need out-of-band/API access). The
hybrid layout **decouples them**. Franklin Bridge does the OS-side work while the
machine keeps running and booting in BIOS mode; the firmware switch becomes a
separate, low-risk step an operator can take later, even much later.

## Status

Feature-complete for **RHEL 8** and validated end-to-end on real hardware: the
same converted disk was booted in **Legacy BIOS**, **UEFI**, and **UEFI with
Secure Boot enabled** (where it self-heals its UEFI boot entry on first boot).
RHEL **9 and 10** are supported by design: they already ship the unified GRUB2
config, so the tool's job there is mainly the partition prerequisites, chosen at
runtime by detecting the current state.

- Language: Python **3.6-3.12**, standard library only (no third-party deps).
- Architecture: **x86_64**.

## Requirements

Run as **root** on the system to be converted. Preflight enforces these and
refuses to proceed otherwise:

- The system is **currently booted in Legacy BIOS mode**.
- RHEL 8/9/10 on x86_64.
- The primary disk has a **separate `/boot`** partition and **unpartitioned free
  space at the end of the disk** (~202 MiB is enough for a default ESP; for a VM,
  grow the virtual disk first).
- Tooling present: `sfdisk`/`parted` (util-linux), `dosfstools`, `grub2-*`, and
  reachable dnf repositories.

> ⚠️ **WARNING!** ⚠️ 
> **This tool rewrites your partition table and bootloader.** It saves a
> copy first, but you should **snapshot or back up the machine** and try it on
> a disposable iinstance before running it on anything you care about.

## Usage

No installation is needed. Run it straight from a checkout:

```bash
# 1. (VMs) grow the disk so there is free space at the end, e.g.,
#    virsh blockresize <domain> --path vda --size 21G

# 2. See exactly what would happen (makes no changes):
sudo ./franklin --dry-run

# 3. Perform the conversion (prompts for confirmation):
sudo ./franklin

# 4. Reboot when convenient to confirm a clean boot with the new layout.
#    Not strictly required as new partitions are already registered with the
#    running kernel, but it verifies the boot path while recovery is easy.
sudo reboot
```

For unattended runs, pass `--yes`. You can also invoke it as a module:
`sudo python3 -m franklin_bridge`.

### Options

| Option | Description |
| --- | --- |
| `--dry-run` | Inspect, plan, and preview every action; make no changes. |
| `--yes`, `-y` | Assume yes; required to make changes non-interactively. |
| `--esp-size SIZE` | EFI System Partition size (e.g. `200M`, `512M`, `1G`; default `200M`). |
| `--disk DEVICE` | Override the primary disk (default: auto-detect from `/boot`). |
| `--backup-dir DIR` | Parent dir for the timestamped backup (default `/var/lib/franklin-bridge`). |
| `-v`, `--verbose` | Verbose output. |
| `--version` | Print version and exit. |

## What it does

The conversion runs as eight ordered, individually idempotent phases (re-running
after an interruption safely resumes):

1. [Preflight & inventory](docs/phase1.md)
2. [Backup & safety net](docs/phase2.md)
3. [Partition surgery](docs/phase3.md) (DOS→GPT, BIOS Boot + ESP)
4. [ESP filesystem & mount](docs/phase4.md)
5. [EFI stack population](docs/phase5.md)
6. [BIOS GRUB reinstall](docs/phase6.md)
7. [Unified GRUB2 config](docs/phase7.md)
8. [Validate & report](docs/phase8.md)

See the [design document](docs/design.md) for goals, scope, the target on-disk
layout, and the full plan.

## Switching to UEFI later

After conversion and a reboot, the system keeps booting in Legacy BIOS mode. When
you're ready, change the machine's firmware from Legacy/BIOS to UEFI. **No extra
OS steps are needed.** The ESP carries the standard `\EFI\BOOT\BOOTX64.EFI`
fallback, so the first UEFI boot works even with empty firmware NVRAM and creates
its own boot entry (compatible with Secure Boot).

## Testing

The pure logic (parsers, planner, config rendering) is covered by a stdlib-only
unit-test suite that runs on Python 3.6-3.12:

```bash
python3 -m pytest        # requires pytest
```

Full destructive, dual-firmware acceptance is exercised against a disposable RHEL
VM rather than in the suite.

## License

[MIT](LICENSE)
