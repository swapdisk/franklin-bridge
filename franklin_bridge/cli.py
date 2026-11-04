"""Command-line entry point for `franklin`.

Phase 1 scope: gather facts, validate, compute and print the plan. Read-only;
the mutating phases are not implemented yet.
"""
import argparse
import re
import sys

from . import __version__
from .inventory import build_facts
from .model import DEFAULT_ESP_SIZE_BYTES, EFI_PACKAGES
from .plan import build_plan
from .probe import Probe
from .report import render_inventory, render_plan, render_validation


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


def build_parser():
    p = argparse.ArgumentParser(
        prog="franklin",
        description="Convert a Legacy-BIOS RHEL system to hybrid BIOS/UEFI boot.",
    )
    p.add_argument("--version", action="version",
                   version="franklin %s" % __version__)
    p.add_argument("--dry-run", action="store_true",
                   help="only inspect and plan; make no changes "
                        "(the only supported mode for now)")
    p.add_argument("--esp-size", type=_size_arg, default=DEFAULT_ESP_SIZE_BYTES,
                   metavar="SIZE",
                   help="EFI System Partition size, e.g. 200M, 512M, 1G "
                        "(default: 200M)")
    p.add_argument("--disk", metavar="DEVICE", default=None,
                   help="override the primary disk (default: auto-detect from /boot)")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="verbose output")
    return p


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

    if not args.dry_run:
        print("")
        print("Note: applying changes is not implemented yet (phases 2-8). "
              "Re-run with --dry-run to silence this note.")
    return 0


def validate_facts(facts, plan):
    # Imported here to keep the module import graph flat and obvious.
    from .validate import validate
    return validate(facts, plan)


if __name__ == "__main__":
    sys.exit(main())
