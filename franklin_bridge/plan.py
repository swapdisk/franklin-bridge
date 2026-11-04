"""Pure plan computation: SystemFacts (+ options) -> ConversionPlan."""
from .model import (
    BIOS_BOOT_SIZE_BYTES,
    DEFAULT_ESP_SIZE_BYTES,
    EFI_PACKAGES,
    SGDISK_CODE_BIOS_BOOT,
    SGDISK_CODE_ESP,
    UNIFIED_STEPS,
    ConversionPlan,
    PartSpec,
)


def build_plan(facts, esp_size_bytes=DEFAULT_ESP_SIZE_BYTES):
    """Compute what the conversion will do, given gathered facts and options.

    This does not inspect whether every unified-config step is already satisfied;
    later phases are individually idempotent and skip work already done. It does
    skip creating partitions that already exist (resume-friendly).
    """
    plan = ConversionPlan(facts.disk.path)
    plan.esp_size_bytes = esp_size_bytes

    plan.convert_to_gpt = facts.disk.pttype == "dos"

    if facts.existing_biosboot is None:
        plan.create_biosboot = PartSpec(
            name="BIOS boot partition",
            size_bytes=BIOS_BOOT_SIZE_BYTES,
            parttype_code=SGDISK_CODE_BIOS_BOOT,
        )

    if facts.existing_esp is None:
        plan.create_esp = PartSpec(
            name="EFI System Partition",
            size_bytes=esp_size_bytes,
            parttype_code=SGDISK_CODE_ESP,
        )

    plan.packages_to_install = [
        pkg for pkg in EFI_PACKAGES if not facts.packages.get(pkg, False)
    ]

    # The BIOS GRUB core image must be (re)written so it lands in the BIOS Boot
    # partition after the GPT conversion.
    plan.needs_bios_grub_reinstall = True

    plan.unified_config_steps = list(UNIFIED_STEPS)
    plan.reboot_required = True
    return plan
