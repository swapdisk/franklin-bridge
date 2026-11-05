"""Integration of the parsers: build_facts over full fixture scenarios."""
from franklin_bridge.inventory import build_facts
from franklin_bridge.model import (
    EFI_PACKAGES,
    FAIL,
    GUID_BIOS_BOOT,
    GUID_ESP,
)
from franklin_bridge.plan import build_plan
from franklin_bridge.validate import validate

from .support import load_raw


def test_build_facts_rhel8_standard():
    facts = build_facts(load_raw("rhel8_dos_standard"), EFI_PACKAGES)

    assert facts.env.os_id == "rhel"
    assert facts.env.os_version_major == "8"
    assert facts.env.firmware_mode == "bios"
    assert facts.disk.path == "/dev/vda"
    assert facts.disk.pttype == "dos"
    assert facts.disk.size_bytes == 41943040 * 512

    assert facts.boot_part is not None
    assert facts.boot_part.device == "/dev/vda1"
    assert facts.boot_part.fs_uuid == "boot-uuid-1111"
    assert facts.boot_part.fstype == "xfs"

    assert facts.root_part is not None
    assert facts.root_part.device == "/dev/vda2"
    assert facts.same_disk_boot_and_root is True

    assert facts.existing_esp is None
    assert facts.existing_biosboot is None
    assert len(facts.free_regions) == 1

    assert facts.packages["grub2-pc"] is True
    assert facts.packages["shim-x64"] is False


def test_build_facts_efi_present_marks_uefi():
    facts = build_facts(load_raw("rhel8_dos_standard", efi_present=True), EFI_PACKAGES)
    assert facts.env.firmware_mode == "uefi"


def test_build_facts_gpt_converted_finds_esp_and_biosboot():
    facts = build_facts(load_raw("gpt_converted"), EFI_PACKAGES)

    assert facts.disk.pttype == "gpt"
    assert facts.existing_biosboot is not None
    assert facts.existing_biosboot.parttype == GUID_BIOS_BOOT
    assert facts.existing_esp is not None
    assert facts.existing_esp.parttype == GUID_ESP
    assert facts.existing_esp.mountpoint == "/boot/efi"

    assert facts.boot_part is not None
    assert facts.boot_part.device == "/dev/vda3"
    assert facts.same_disk_boot_and_root is True


def test_build_facts_rhel8_vm_nogrow_real_capture():
    # Captured verbatim from the r8iso VM BEFORE the disk was grown:
    # lsblk sizes are strings, there is an sr0 ROM device, findmnt is a deep
    # tree, and the only free space is a tiny gap at the START (not the end).
    facts = build_facts(load_raw("rhel8_vm_nogrow"), EFI_PACKAGES)

    # String sizes parse to ints; ROM device is ignored for disk selection.
    assert facts.disk.path == "/dev/vda"
    assert facts.disk.size_bytes == 41943040 * 512
    assert facts.disk.pttype == "dos"

    # Deep findmnt tree still resolves /boot and root.
    assert facts.boot_part is not None and facts.boot_part.device == "/dev/vda1"
    assert facts.root_part is not None and facts.root_part.device == "/dev/vda2"
    assert facts.same_disk_boot_and_root is True

    # The one free region is at the start and does NOT reach the disk end.
    assert len(facts.free_regions) == 1
    assert facts.free_regions[0].end_sector < facts.disk.size_bytes // 512 - 2048

    # Preflight must fail precisely on free space (disk not grown yet).
    plan = build_plan(facts)
    result = validate(facts, plan)
    assert not result.ok
    free = [c for c in result.checks if c.name == "free_space"][0]
    assert free.status == FAIL
    # Everything else is fine.
    other_fails = [c for c in result.failures if c.name != "free_space"]
    assert other_fails == []


def test_build_facts_thin_lvm_is_single_disk():
    # Thin-pool root LV sits several dm layers above the disk, and its pkname is
    # a kernel name (dm-N), not a friendly name. Ancestry must still reach vda.
    facts = build_facts(load_raw("rhel8_thin_lvm"), EFI_PACKAGES)

    assert facts.disk.path == "/dev/vda"
    assert facts.disk.pttype == "dos"
    assert facts.boot_part is not None and facts.boot_part.device == "/dev/vda1"
    assert facts.root_part is not None and facts.root_part.device == "/dev/vda2"
    assert facts.same_disk_boot_and_root is True

    # The whole preflight passes for this layout (disk was grown: free at end).
    plan = build_plan(facts)
    result = validate(facts, plan)
    assert result.ok, [c for c in result.checks if c.status == FAIL]


def test_build_facts_sda_naming():
    # Reuse the standard fixtures but rename the disk device throughout.
    raw = load_raw("rhel8_dos_standard")
    raw = raw._replace(
        lsblk_json=raw.lsblk_json.replace("vda", "sda"),
        findmnt_json=raw.findmnt_json.replace("vda", "sda"),
        parted_free=raw.parted_free.replace("vda", "sda"),
    )
    facts = build_facts(raw, EFI_PACKAGES)
    assert facts.disk.path == "/dev/sda"
    assert facts.boot_part.device == "/dev/sda1"
    assert facts.root_part.device == "/dev/sda2"
