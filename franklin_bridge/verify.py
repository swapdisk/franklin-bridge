"""Phase 8 - Validate & report (read-only).

Re-probes the converted system and verifies the hybrid-boot end-state: GPT label,
the BIOS Boot + EFI System partitions, a mounted and populated ESP (including the
UEFI fallback), the bootstrap and real GRUB configs, a real grubenv, the /etc
symlinks, and the BIOS GRUB modules. Produces a ValidationResult and the final
operator summary.
"""
from typing import NamedTuple, Optional

from .esp import fstab_has_mount
from .model import FAIL, PASS, ValidationResult
from .unified import ETC_SYMLINK_TARGET, GRUB_HOME, GRUBENV, REAL_CFG


class EndStateObs(NamedTuple):
    grubx64: bool
    shimx64: bool
    fallback: bool
    bootstrap_text: str
    real_cfg: bool
    grubenv_exists: bool
    grubenv_islink: bool
    etc_grub2_target: Optional[str]
    etc_grub2efi_target: Optional[str]
    i386pc_module: bool
    fstab_has_esp: bool


def _add(result, name, ok, pass_msg, fail_msg):
    result.add(name, PASS if ok else FAIL, pass_msg if ok else fail_msg)


def check_end_state(facts, obs, boot_uuid):
    """Verify the converted end-state (pure). Returns a ValidationResult."""
    r = ValidationResult()

    _add(r, "gpt", facts.disk.pttype == "gpt",
         "disk is GPT",
         "disk is not GPT (%s)" % facts.disk.pttype)

    _add(r, "bios_boot_partition", facts.existing_biosboot is not None,
         "BIOS Boot partition present",
         "BIOS Boot partition missing")

    esp = facts.existing_esp
    _add(r, "esp_partition", esp is not None,
         "EFI System Partition present",
         "EFI System Partition missing")

    esp_ok = (esp is not None and esp.fstype == "vfat"
              and esp.mountpoint == "/boot/efi")
    _add(r, "esp_mounted", esp_ok,
         "ESP is vfat, mounted at /boot/efi",
         "ESP not mounted as vfat at /boot/efi")

    _add(r, "esp_populated", obs.grubx64 and obs.shimx64,
         "ESP has grubx64.efi + shimx64.efi",
         "ESP missing grubx64.efi/shimx64.efi")

    _add(r, "uefi_fallback", obs.fallback,
         "UEFI fallback EFI/BOOT/BOOTX64.EFI present",
         "UEFI fallback EFI/BOOT/BOOTX64.EFI missing")

    bootstrap_ok = bool(boot_uuid) and all(
        s in obs.bootstrap_text
        for s in ("configfile", "--fs-uuid", boot_uuid or "\0"))
    _add(r, "bootstrap_config", bootstrap_ok,
         "EFI bootstrap chains to real config by /boot UUID",
         "EFI bootstrap config missing or incorrect")

    _add(r, "real_config", obs.real_cfg,
         "real GRUB config present",
         "real GRUB config missing")

    _add(r, "grubenv_real", obs.grubenv_exists and not obs.grubenv_islink,
         "grubenv is a real file",
         "grubenv missing or is a symlink")

    symlinks_ok = (obs.etc_grub2_target == ETC_SYMLINK_TARGET
                   and obs.etc_grub2efi_target == ETC_SYMLINK_TARGET)
    _add(r, "etc_symlinks", symlinks_ok,
         "/etc/grub2.cfg and /etc/grub2-efi.cfg point to the real config",
         "/etc/grub2*.cfg symlinks incorrect")

    _add(r, "bios_grub_modules", obs.i386pc_module,
         "BIOS GRUB modules installed",
         "BIOS GRUB modules missing")

    _add(r, "fstab_esp", obs.fstab_has_esp,
         "fstab has the ESP entry",
         "fstab missing the ESP entry")

    return r


def gather_end_state(executor, plan):
    """Collect end-state observations from the live system (impure)."""
    esp = plan.esp_mountpoint
    redhat = esp + "/EFI/redhat"
    return EndStateObs(
        grubx64=executor.exists(redhat + "/grubx64.efi"),
        shimx64=executor.exists(redhat + "/shimx64.efi"),
        fallback=executor.exists(esp + "/EFI/BOOT/BOOTX64.EFI"),
        bootstrap_text=executor.read_text(redhat + "/grub.cfg"),
        real_cfg=executor.exists(REAL_CFG),
        grubenv_exists=executor.exists(GRUBENV),
        grubenv_islink=executor.islink(GRUBENV),
        etc_grub2_target=executor.readlink("/etc/grub2.cfg"),
        etc_grub2efi_target=executor.readlink("/etc/grub2-efi.cfg"),
        i386pc_module=executor.exists(GRUB_HOME + "/i386-pc/normal.mod"),
        fstab_has_esp=fstab_has_mount(executor.read_text("/etc/fstab"), "/boot/efi"),
    )


def execute_validation(executor, facts, plan, reprobe=None):
    """Perform Phase 8. Returns a ValidationResult, or None in dry-run."""
    if getattr(executor, "dry_run", False):
        executor.log("[dry-run] would re-probe and verify the converted end-state")
        return None
    fresh = reprobe() if reprobe is not None else _reprobe(facts)
    obs = gather_end_state(executor, plan)
    boot_uuid = fresh.boot_part.fs_uuid if fresh.boot_part else None
    return check_end_state(fresh, obs, boot_uuid)


def _reprobe(facts):
    from .inventory import build_facts
    from .model import EFI_PACKAGES
    from .probe import Probe
    raw = Probe().collect(disk_override=facts.disk.path)
    return build_facts(raw, EFI_PACKAGES)
