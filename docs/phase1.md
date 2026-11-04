# Phase 1 — Preflight & Inventory

> Part of the plan in [`design.md`](design.md) §6. Phase 1 is **read-only**: it
> gathers facts, validates preconditions, computes the conversion plan, and
> prints a report. It mutates nothing.

## Decisions (settled)

1. **Free-space detection** via `parted -m -s <disk> unit s print free` (explicit
   free regions), cross-checked against disk size.
2. **Unsupported layouts fail fast** in v1 with a clear message: no separate
   `/boot` partition, or `/boot` and root on different disks.
3. **Phase 1 is strictly read-only.** Missing base tools (`gdisk`/`sgdisk`,
   `dosfstools`) are *reported*; installs happen in later phases.
4. **Single command: `franklin`** with flags `--dry-run`, `--esp-size`,
   `--disk`, `-v`. (Until the mutating phases exist, every run is effectively a
   preflight.)
5. **Data model:** immutable `typing.NamedTuple` records for gathered facts
   (3.6-safe; no `@dataclass`, which is 3.7+); one plain, mutable class for the
   `ConversionPlan` we build up.

## Pure / impure boundary

Each detector is split so the parsing is unit-testable without running commands:

- **Collectors (impure, `probe.py`)** run the real commands and return raw
  stdout as strings into a `RawInputs` record.
- **Parsers (pure, `inventory.py`)** turn that raw text into structured facts.

Tests feed fixture text straight into the parsers and feed structured
`SystemFacts` into the planner/validator — **no subprocess mocking**.

## Modules

```
franklin_bridge/
  __init__.py
  __main__.py     # enables `python -m franklin_bridge`
  model.py        # NamedTuple records + ConversionPlan/ValidationResult + constants
  probe.py        # impure collectors -> RawInputs
  inventory.py    # pure parsers + build_facts() -> SystemFacts
  plan.py         # pure build_plan() -> ConversionPlan
  validate.py     # pure validate() -> ValidationResult
  report.py       # render facts/plan/checks for the user
  cli.py          # argparse + wiring; main()
franklin           # thin launcher (python3 -> cli.main())
tests/
  support.py      # fixture loaders + make_facts() helper
  fixtures/<scenario>/{os-release,lsblk.json,findmnt.json,parted-free.txt,rpm-q.txt}
  test_parsers.py test_build_facts.py test_plan.py test_validate.py
```

## Key data structures

- `EnvFacts(is_root, arch, os_id, os_version_major, firmware_mode)`
- `DiskFacts(path, size_bytes, sector_size, pttype)`
- `Partition(number, device, start_sector, end_sector, size_bytes, parttype,
  fstype, fs_uuid, mountpoint, flags)`
- `FreeRegion(start_sector, end_sector, size_bytes)`
- `SystemFacts(env, disk, partitions, boot_part, root_part,
  same_disk_boot_and_root, existing_esp, existing_biosboot, free_regions, tools,
  packages)`
- `ConversionPlan` (plain class): `convert_to_gpt`, `create_biosboot`,
  `create_esp`, `esp_size_bytes`, `packages_to_install`,
  `needs_bios_grub_reinstall`, `unified_config_steps`, `reboot_required`
- `ValidationResult`: list of `Check(name, status, message)` where status is
  `pass`/`warn`/`fail`; `.ok` is true iff no fails.

## Validation checks

Hard fail: not root · arch ≠ x86_64 · OS not RHEL 8/9/10 · firmware already UEFI
· disk not DOS (GPT ⇒ warn, may be resuming) · no separate `/boot` · `/boot` and
root on different disks · insufficient free space · no free space **at the end of
the disk** (GPT needs the secondary header there) · essential tool missing.

Warn: EFI packages not yet installed (installed in Phase 5).
