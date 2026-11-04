"""Unit tests for the pure parsers in franklin_bridge.inventory."""
from franklin_bridge.inventory import (
    parse_findmnt,
    parse_lsblk,
    parse_os_release,
    parse_parted,
    parse_rpm_q,
    select_primary_disk,
    _part_device,
)
from franklin_bridge.model import EFI_PACKAGES

from .support import read_fixture


def test_parse_os_release_rhel8():
    os_id, major = parse_os_release(read_fixture("rhel8_dos_standard", "os-release"))
    assert os_id == "rhel"
    assert major == "8"


def test_parse_os_release_handles_blank_and_comments():
    text = "# comment\n\nID=fedora\nVERSION_ID=39\n"
    assert parse_os_release(text) == ("fedora", "39")


def test_parse_findmnt_flattens_tree():
    mounts = parse_findmnt(read_fixture("rhel8_dos_standard", "findmnt.json"))
    assert mounts["/"] == "/dev/mapper/rhel-root"
    assert mounts["/boot"] == "/dev/vda1"


def test_parse_lsblk_mountpoint_string_form():
    nodes = parse_lsblk(read_fixture("rhel8_dos_standard", "lsblk.json"))
    by_name = dict((n["name"], n) for n in nodes)
    assert by_name["vda"]["type"] == "disk"
    assert by_name["vda1"]["mountpoint"] == "/boot"
    assert by_name["vda1"]["pkname"] == "vda"
    assert by_name["rhel-root"]["mountpoint"] == "/"


def test_parse_lsblk_mountpoints_list_form():
    nodes = parse_lsblk(read_fixture("gpt_converted", "lsblk.json"))
    by_name = dict((n["name"], n) for n in nodes)
    # RHEL 9+ emits a "mountpoints" list; parser should collapse it.
    assert by_name["vda2"]["mountpoint"] == "/boot/efi"
    assert by_name["vda3"]["mountpoint"] == "/boot"
    # parttype should be lowercased.
    assert by_name["vda1"]["parttype"] == "21686148-6449-6e6f-744e-656564454649"


def test_parse_parted_geometry_and_free():
    disk = parse_parted(read_fixture("rhel8_dos_standard", "parted-free.txt"))
    assert disk.path == "/dev/vda"
    assert disk.sector_size == 512
    assert disk.size_sectors == 41943040
    assert disk.pttype == "dos"  # msdos normalized
    assert len(disk.parts) == 2
    assert disk.parts[0].number == 1
    assert disk.parts[0].flags == ("boot",)
    assert len(disk.frees) == 1
    assert disk.frees[0].start_sector == 37750784
    assert disk.frees[0].end_sector == 41943039


def test_parse_parted_gpt_flags():
    disk = parse_parted(read_fixture("gpt_converted", "parted-free.txt"))
    assert disk.pttype == "gpt"
    by_num = dict((p.number, p) for p in disk.parts)
    assert by_num[1].flags == ("bios_grub",)
    assert by_num[2].flags == ("boot", "esp")


def test_parse_rpm_q_mixed():
    pkgs = parse_rpm_q(read_fixture("rhel8_dos_standard", "rpm-q.txt"), EFI_PACKAGES)
    assert pkgs["grub2-efi-x64"] is False
    assert pkgs["shim-x64"] is False
    assert pkgs["grub2-pc"] is True


def test_parse_rpm_q_all_installed():
    pkgs = parse_rpm_q(read_fixture("gpt_converted", "rpm-q.txt"), EFI_PACKAGES)
    assert all(pkgs[p] for p in EFI_PACKAGES)


def test_select_primary_disk_from_boot():
    nodes = parse_lsblk(read_fixture("rhel8_dos_standard", "lsblk.json"))
    mounts = parse_findmnt(read_fixture("rhel8_dos_standard", "findmnt.json"))
    assert select_primary_disk(nodes, mounts, None) == "/dev/vda"


def test_select_primary_disk_override_wins():
    nodes = parse_lsblk(read_fixture("rhel8_dos_standard", "lsblk.json"))
    mounts = parse_findmnt(read_fixture("rhel8_dos_standard", "findmnt.json"))
    assert select_primary_disk(nodes, mounts, "/dev/sdz") == "/dev/sdz"


def test_part_device_naming():
    assert _part_device("/dev/vda", 1) == "/dev/vda1"
    assert _part_device("/dev/sda", 2) == "/dev/sda2"
    assert _part_device("/dev/nvme0n1", 3) == "/dev/nvme0n1p3"
