"""Pure preflight validation: SystemFacts (+ plan) -> ValidationResult."""
from .model import (
    END_SLACK_SECTORS,
    ESSENTIAL_TOOLS,
    FAIL,
    GPT_SECONDARY_RESERVE_BYTES,
    PASS,
    RHEL_FAMILY_IDS,
    SUPPORTED_MAJORS,
    WARN,
    ValidationResult,
)


def _fmt_mib(num_bytes):
    return "%.0f MiB" % (num_bytes / (1024.0 * 1024.0))


def validate(facts, plan):
    """Run all preflight checks. Returns a ValidationResult (.ok if no fails)."""
    r = ValidationResult()
    env = facts.env

    r.add(
        "root",
        PASS if env.is_root else FAIL,
        "running as root" if env.is_root else "must be run as root",
    )

    r.add(
        "arch",
        PASS if env.arch == "x86_64" else FAIL,
        "architecture is x86_64" if env.arch == "x86_64"
        else "unsupported architecture %r (x86_64 only)" % env.arch,
    )

    os_ok = env.os_id in RHEL_FAMILY_IDS and env.os_version_major in SUPPORTED_MAJORS
    r.add(
        "os",
        PASS if os_ok else FAIL,
        "OS is %s %s" % (env.os_id, env.os_version_major) if os_ok
        else "unsupported OS %r %r (RHEL 8/9/10 only)"
             % (env.os_id, env.os_version_major),
    )

    r.add(
        "firmware",
        PASS if env.firmware_mode == "bios" else FAIL,
        "booted in BIOS mode" if env.firmware_mode == "bios"
        else "system is booted in UEFI mode; this tool converts BIOS systems",
    )

    # Partition table.
    if facts.disk.pttype == "unknown":
        r.add(
            "partition_table", FAIL,
            "could not read the partition table of %s "
            "(need root, and parted must be installed)" % facts.disk.path,
        )
    elif facts.disk.pttype == "dos":
        r.add("partition_table", PASS, "disk %s has a DOS table" % facts.disk.path)
    elif facts.disk.pttype == "gpt":
        r.add(
            "partition_table", WARN,
            "disk %s is already GPT; a previous run may be resuming" % facts.disk.path,
        )
    else:
        r.add(
            "partition_table", FAIL,
            "disk %s has unsupported partition table %r"
            % (facts.disk.path, facts.disk.pttype),
        )

    # Separate /boot partition.
    if facts.boot_part is not None:
        r.add("boot_partition", PASS, "/boot is on %s" % facts.boot_part.device)
    else:
        r.add(
            "boot_partition", FAIL,
            "no separate /boot partition found (unsupported in this version)",
        )

    # /boot and root on the same single disk.
    if facts.same_disk_boot_and_root:
        r.add("single_disk", PASS, "/boot and root are on the same disk")
    else:
        r.add("single_disk", FAIL, _single_disk_failure_message(facts))

    # Essential tools.
    missing = [t for t in ESSENTIAL_TOOLS if not facts.tools.get(t)]
    if missing:
        r.add(
            "tools", FAIL,
            "missing required tool(s): %s" % ", ".join(sorted(missing)),
        )
    else:
        r.add("tools", PASS, "all required tools present")

    # EFI packages (installed later; warn only).
    missing_pkgs = [p for p in plan.packages_to_install]
    if missing_pkgs:
        r.add(
            "packages", WARN,
            "will install: %s" % ", ".join(missing_pkgs),
        )
    else:
        r.add("packages", PASS, "EFI packages already installed")

    _check_free_space(facts, plan, r)
    return r


def _single_disk_failure_message(facts):
    boot = getattr(facts, "boot_disks", ()) or ()
    root = getattr(facts, "root_disks", ()) or ()
    if len(root) > 1 or len(boot) > 1:
        spans = ", ".join(sorted(set(boot) | set(root)))
        return ("/boot or root storage spans multiple disks (%s); "
                "unsupported in this version" % spans)
    if boot and root and set(boot) != set(root):
        return ("/boot (%s) and root (%s) are on different disks; "
                "unsupported in this version"
                % (", ".join(boot), ", ".join(root)))
    return ("could not confirm /boot and root share a single disk; "
            "unsupported in this version")


def _check_free_space(facts, plan, r):
    sector_size = facts.disk.sector_size or 512
    disk_sectors = facts.disk.size_bytes // sector_size

    need = GPT_SECONDARY_RESERVE_BYTES
    if plan.create_biosboot is not None:
        need += plan.create_biosboot.size_bytes
    if plan.create_esp is not None:
        need += plan.create_esp.size_bytes

    total_free = sum(region.size_bytes for region in facts.free_regions)

    if total_free < need:
        r.add(
            "free_space", FAIL,
            "need ~%s of free space but only %s is available; grow the disk first"
            % (_fmt_mib(need), _fmt_mib(total_free)),
        )
        return

    # The secondary GPT header/table must live at the very end of the disk.
    end_threshold = disk_sectors - END_SLACK_SECTORS
    has_end_free = any(
        region.end_sector >= end_threshold for region in facts.free_regions
    )
    if not has_end_free:
        r.add(
            "free_space", FAIL,
            "no free space at the end of the disk for the GPT secondary header; "
            "grow the disk so the free space is at the end",
        )
        return

    r.add(
        "free_space", PASS,
        "%s free (need ~%s), including space at end of disk"
        % (_fmt_mib(total_free), _fmt_mib(need)),
    )
