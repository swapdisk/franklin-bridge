"""Unit tests for build_plan (pure)."""
from franklin_bridge.inventory import build_facts
from franklin_bridge.model import (
    BIOS_BOOT_SIZE_BYTES,
    DEFAULT_ESP_SIZE_BYTES,
    EFI_PACKAGES,
    MIB,
    SGDISK_CODE_BIOS_BOOT,
    SGDISK_CODE_ESP,
)
from franklin_bridge.plan import build_plan

from .support import load_raw, make_facts


def test_plan_standard_creates_everything():
    plan = build_plan(make_facts())
    assert plan.convert_to_gpt is True
    assert plan.create_biosboot is not None
    assert plan.create_biosboot.size_bytes == BIOS_BOOT_SIZE_BYTES
    assert plan.create_biosboot.parttype_code == SGDISK_CODE_BIOS_BOOT
    assert plan.create_esp is not None
    assert plan.create_esp.parttype_code == SGDISK_CODE_ESP
    assert plan.esp_size_bytes == DEFAULT_ESP_SIZE_BYTES
    # grub2-pc is already installed on a BIOS system; only the EFI packages remain.
    assert set(plan.packages_to_install) == {"grub2-efi-x64", "shim-x64"}
    assert plan.needs_bios_grub_reinstall is True
    assert plan.unified_config_steps  # non-empty


def test_plan_respects_custom_esp_size():
    plan = build_plan(make_facts(), esp_size_bytes=512 * MIB)
    assert plan.esp_size_bytes == 512 * MIB
    assert plan.create_esp.size_bytes == 512 * MIB


def test_plan_skips_installed_packages():
    facts = make_facts(packages={p: True for p in EFI_PACKAGES})
    plan = build_plan(facts)
    assert plan.packages_to_install == []


def test_plan_gpt_converted_skips_partition_creation():
    facts = build_facts(load_raw("gpt_converted"), EFI_PACKAGES)
    plan = build_plan(facts)
    assert plan.convert_to_gpt is False
    assert plan.create_biosboot is None
    assert plan.create_esp is None
    assert plan.packages_to_install == []
