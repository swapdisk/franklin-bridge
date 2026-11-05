"""Command-line entry point for `franklin`.

Flow:
  1. Always: probe -> build facts -> plan -> validate -> print report.
  2. If validation fails, exit non-zero.
  3. --dry-run: additionally preview the backup actions, then stop.
  4. Otherwise (apply mode): confirm, then run the implemented phases
     (currently Phase 2, the safety backup). The destructive phases 3-8 are
     not implemented yet.
"""
import argparse
import datetime
import os
import re
import sys

from . import __version__
from .backup import execute_backup, plan_backup
from .biosgrub import execute_bios_grub
from .efistack import execute_efistack
from .esp import execute_esp
from .executor import Executor
from .inventory import build_facts
from .model import DEFAULT_ESP_SIZE_BYTES, EFI_PACKAGES
from .partition import execute_partitioning
from .plan import build_plan
from .probe import Probe
from .report import render_inventory, render_plan, render_validation
from .unified import execute_unified_config
from .verify import execute_validation


DEFAULT_BACKUP_DIR = "/var/lib/franklin-bridge"

_SIZE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kKmMgGtT]?)(?:i?[bB])?\s*$")
_SIZE_MULT = {
    "": 1024 * 1024,          # bare number means MiB
    "k": 1024,
    "m": 1024 * 1024,
    "g": 1024 * 1024 * 1024,
    "t": 1024 * 1024 * 1024 * 1024,
}


def parse_size(text):
    """Parse a size like '200', '200M', '512MiB', '1G' into bytes (MiB default)."""
    m = _SIZE_RE.match(text)
    if not m:
        raise ValueError("invalid size %r" % text)
    value = float(m.group(1))
    mult = _SIZE_MULT[m.group(2).lower()]
    return int(value * mult)


def _size_arg(text):
    try:
        return parse_size(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc))


def confirm(prompt, assume_yes):
    """Ask for confirmation. Non-interactive runs must pass --yes."""
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return False
    try:
        answer = input("%s [y/N] " % prompt)
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes")


def build_parser():
    p = argparse.ArgumentParser(
        prog="franklin",
        description="Convert a Legacy-BIOS RHEL system to hybrid BIOS/UEFI boot.",
    )
    p.add_argument("--version", action="version",
                   version="franklin %s" % __version__)
    p.add_argument("--dry-run", action="store_true",
                   help="inspect, plan, and preview actions; make no changes")
    p.add_argument("--yes", "-y", action="store_true",
                   help="assume yes; required to make changes non-interactively")
    p.add_argument("--esp-size", type=_size_arg, default=DEFAULT_ESP_SIZE_BYTES,
                   metavar="SIZE",
                   help="EFI System Partition size, e.g. 200M, 512M, 1G "
                        "(default: 200M)")
    p.add_argument("--disk", metavar="DEVICE", default=None,
                   help="override the primary disk (default: auto-detect from /boot)")
    p.add_argument("--backup-dir", metavar="DIR", default=DEFAULT_BACKUP_DIR,
                   help="parent directory for the timestamped backup "
                        "(default: %s)" % DEFAULT_BACKUP_DIR)
    p.add_argument("-v", "--verbose", action="store_true",
                   help="verbose output")
    return p


def _backup_dir(parent):
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return os.path.join(parent, "backup-%s" % ts)


def main(argv=None):
    args = build_parser().parse_args(argv)

    probe = Probe()
    raw = probe.collect(disk_override=args.disk)
    facts = build_facts(raw, EFI_PACKAGES)
    plan = build_plan(facts, esp_size_bytes=args.esp_size)
    result = validate_facts(facts, plan)

    print(render_inventory(facts))
    print("")
    print(render_plan(plan))
    print("")
    print(render_validation(result))

    if not result.ok:
        return 1

    backup_dir = _backup_dir(args.backup_dir)

    if args.dry_run:
        dry = Executor(dry_run=True)
        print("")
        print("== Backup (dry-run preview) ==")
        execute_backup(dry, plan_backup(facts, backup_dir))
        print("")
        print("== Partitioning (dry-run preview) ==")
        execute_partitioning(dry, facts, plan)
        print("")
        print("== ESP filesystem & mount (dry-run preview) ==")
        execute_esp(dry, facts, plan)
        print("")
        print("== EFI stack population (dry-run preview) ==")
        execute_efistack(dry, facts, plan)
        print("")
        print("== BIOS GRUB reinstall (dry-run preview) ==")
        execute_bios_grub(dry, facts, plan)
        print("")
        print("== Unified GRUB config (dry-run preview) ==")
        execute_unified_config(dry, facts, plan)
        print("")
        print("== Validation (dry-run preview) ==")
        execute_validation(dry, facts, plan)
        return 0

    # Apply mode.
    print("")
    prompt = ("This will MODIFY %s: take a safety backup, then convert the "
              "partition table to GPT and create new partitions. Proceed?"
              % facts.disk.path)
    if not confirm(prompt, args.yes):
        print("Aborted: no confirmation given "
              "(use --yes for non-interactive runs).")
        return 1

    executor = Executor(dry_run=False)

    print("")
    print("== Phase 2: safety backup ==")
    summary = execute_backup(executor, plan_backup(facts, backup_dir))
    print("Backup complete: %s" % summary["backup_dir"])
    if summary["skipped"]:
        print("  (not present, skipped: %s)" % ", ".join(summary["skipped"]))

    print("")
    print("== Phase 3: partition surgery ==")
    execute_partitioning(executor, facts, plan)

    print("")
    print("== Phase 4: ESP filesystem & mount ==")
    execute_esp(executor, facts, plan)

    print("")
    print("== Phase 5: EFI stack population ==")
    execute_efistack(executor, facts, plan)

    print("")
    print("== Phase 6: BIOS GRUB reinstall ==")
    execute_bios_grub(executor, facts, plan)

    print("")
    print("== Phase 7: unified GRUB config ==")
    execute_unified_config(executor, facts, plan)

    print("")
    print("== Phase 8: validate & report ==")
    result = execute_validation(executor, facts, plan)
    print("")
    print(render_validation(result, title="End-state validation",
                            verb="Validation"))

    print("")
    print(_completion_summary(facts, result.ok))
    return 0 if result.ok else 1


def validate_facts(facts, plan):
    from .validate import validate
    return validate(facts, plan)


def _completion_summary(facts, ok):
    lines = []
    if ok:
        lines.append("Conversion complete: %s is now configured for hybrid "
                     "BIOS/UEFI boot." % facts.disk.path)
    else:
        lines.append("Conversion ran but end-state validation found problems "
                     "(see above). Review before rebooting.")
    lines.append("")
    lines.append("Next steps:")
    lines.append("  1. Reboot now to finalize the new partition table "
                 "(the kernel is still using the pre-conversion view).")
    lines.append("  2. The system will continue to boot in Legacy BIOS mode as "
                 "before.")
    lines.append("  3. Whenever convenient, switch the firmware from Legacy/BIOS "
                 "to UEFI. No extra steps are needed: the system boots via the "
                 "EFI fallback and creates its own UEFI boot entry on the first "
                 "UEFI boot.")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
