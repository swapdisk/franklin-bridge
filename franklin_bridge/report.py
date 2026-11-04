"""Render inventory, plan, and validation results as human-readable text."""
from .model import FAIL, PASS, WARN

_STATUS_MARK = {PASS: "[ OK ]", WARN: "[WARN]", FAIL: "[FAIL]"}


def _mib(num_bytes):
    return "%.0f MiB" % (num_bytes / (1024.0 * 1024.0))


def _gib(num_bytes):
    return "%.1f GiB" % (num_bytes / (1024.0 * 1024.0 * 1024.0))


def render_inventory(facts):
    lines = ["== System inventory =="]
    env = facts.env
    lines.append(
        "  OS: %s %s   arch: %s   firmware: %s   root: %s"
        % (env.os_id or "?", env.os_version_major or "?", env.arch,
           env.firmware_mode, "yes" if env.is_root else "no")
    )
    lines.append(
        "  Disk: %s   %s   table: %s   sector: %dB"
        % (facts.disk.path, _gib(facts.disk.size_bytes),
           facts.disk.pttype or "?", facts.disk.sector_size)
    )
    lines.append("  Partitions:")
    for p in facts.partitions:
        lines.append(
            "    %-14s %8s  %-12s %-8s %s"
            % (p.device, _mib(p.size_bytes), p.fstype or "-",
               p.mountpoint or "-", p.parttype or "")
        )
    if facts.free_regions:
        lines.append("  Free space:")
        for region in facts.free_regions:
            lines.append(
                "    sectors %d-%d  (%s)"
                % (region.start_sector, region.end_sector, _mib(region.size_bytes))
            )
    else:
        lines.append("  Free space: none")
    lines.append(
        "  /boot: %s   existing ESP: %s   existing BIOS Boot: %s"
        % (
            facts.boot_part.device if facts.boot_part else "none",
            facts.existing_esp.device if facts.existing_esp else "none",
            facts.existing_biosboot.device if facts.existing_biosboot else "none",
        )
    )
    return "\n".join(lines)


def render_plan(plan):
    lines = ["== Conversion plan =="]
    lines.append("  Target disk: %s" % plan.disk_path)
    lines.append("  Convert DOS -> GPT: %s" % ("yes" if plan.convert_to_gpt else "no"))
    if plan.create_biosboot:
        lines.append(
            "  Create BIOS Boot partition: %s (%s)"
            % (_mib(plan.create_biosboot.size_bytes), plan.create_biosboot.parttype_code)
        )
    else:
        lines.append("  Create BIOS Boot partition: skip (already present)")
    if plan.create_esp:
        lines.append(
            "  Create EFI System Partition: %s (%s), mount %s"
            % (_mib(plan.create_esp.size_bytes), plan.create_esp.parttype_code,
               plan.esp_mountpoint)
        )
    else:
        lines.append("  Create EFI System Partition: skip (already present)")
    lines.append(
        "  Install packages: %s"
        % (", ".join(plan.packages_to_install) if plan.packages_to_install else "none")
    )
    lines.append(
        "  Reinstall BIOS GRUB: %s"
        % ("yes" if plan.needs_bios_grub_reinstall else "no")
    )
    lines.append("  Unified-config steps: %s" % ", ".join(plan.unified_config_steps))
    lines.append("  Reboot required afterward: %s" % ("yes" if plan.reboot_required else "no"))
    return "\n".join(lines)


def render_validation(result):
    lines = ["== Preflight checks =="]
    for c in result.checks:
        lines.append("  %s %-16s %s" % (_STATUS_MARK.get(c.status, "[????]"),
                                        c.name, c.message))
    lines.append("")
    if result.ok:
        lines.append("Preflight PASSED." if not result.warnings
                     else "Preflight PASSED with warnings.")
    else:
        lines.append("Preflight FAILED: %d problem(s) must be resolved."
                     % len(result.failures))
    return "\n".join(lines)
