"""Immutable data model + constants for Franklin Bridge preflight and planning.

Python 3.6 compatible on purpose:
  * uses ``typing.NamedTuple`` (``@dataclass`` is 3.7+),
  * uses ``typing`` generics in annotations (builtin ``list[...]`` subscription
    is 3.9+),
  * f-strings are fine (3.6+); avoids walrus / positional-only params (3.8+).
"""
from typing import Dict, NamedTuple, Optional, Tuple


# --- Sizes --------------------------------------------------------------------

MIB = 1024 * 1024
GIB = 1024 * 1024 * 1024

# The BIOS Boot partition is a fixed small size; 1 MiB is conventional.
BIOS_BOOT_SIZE_BYTES = 1 * MIB
# Default EFI System Partition size (overridable via --esp-size).
DEFAULT_ESP_SIZE_BYTES = 200 * MIB
# Room GPT needs at the very end of the disk for the secondary header + table.
# 33 sectors is the spec minimum; we reserve 1 MiB for alignment headroom.
GPT_SECONDARY_RESERVE_BYTES = 1 * MIB
# When deciding whether a free region reaches the end of the disk, allow this
# much slack (sectors) for the secondary GPT that parted may already exclude.
END_SLACK_SECTORS = 2048


# --- GPT partition type GUIDs (lowercased) ------------------------------------

GUID_ESP = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
GUID_BIOS_BOOT = "21686148-6449-6e6f-744e-656564454649"


# --- sgdisk type codes used when creating partitions --------------------------

SGDISK_CODE_ESP = "ef00"
SGDISK_CODE_BIOS_BOOT = "ef02"


# --- Package / tool expectations ----------------------------------------------

# Packages the later phases install to populate the EFI stack and BIOS GRUB.
EFI_PACKAGES = ("grub2-efi-x64", "shim-x64", "grub2-pc")

# Tools that must already be present for the conversion to be possible.
ESSENTIAL_TOOLS = (
    "sgdisk",
    "sfdisk",
    "parted",
    "blkid",
    "dd",
    "mkfs.vfat",
    "partx",
    "grub2-install",
    "grub2-mkconfig",
    "grub2-editenv",
    "grub2-probe",
    "grub2-mkrelpath",
)

# OS IDs (from /etc/os-release) treated as the RHEL family.
RHEL_FAMILY_IDS = ("rhel", "centos", "almalinux", "rocky")
SUPPORTED_MAJORS = ("8", "9", "10")


# --- Check statuses -----------------------------------------------------------

PASS = "pass"
WARN = "warn"
FAIL = "fail"


# --- Unified-config steps (planned; applied + made idempotent in later phases) -

UNIFIED_STEPS = (
    "bootstrap_grubcfg",   # /boot/efi/EFI/redhat/grub.cfg -> real config
    "grubenv_realfile",    # ensure /boot/grub2/grubenv is a real file
    "etc_grub2_symlinks",  # /etc/grub2.cfg + /etc/grub2-efi.cfg
    "efi_fallback",        # /boot/efi/EFI/BOOT/BOOTX64.EFI fallback
    "grub2_mkconfig",      # regenerate /boot/grub2/grub.cfg
)


# --- Immutable fact records ---------------------------------------------------

class EnvFacts(NamedTuple):
    is_root: bool
    arch: str
    os_id: str
    os_version_major: str
    firmware_mode: str  # "bios" | "uefi"


class DiskFacts(NamedTuple):
    path: str
    size_bytes: int
    sector_size: int
    pttype: str  # "dos" | "gpt" | other


class Partition(NamedTuple):
    number: int
    device: str
    start_sector: int
    end_sector: int
    size_bytes: int
    parttype: Optional[str]   # GPT GUID or DOS hex id, lowercased
    fstype: Optional[str]
    fs_uuid: Optional[str]
    mountpoint: Optional[str]
    flags: Tuple[str, ...]


class FreeRegion(NamedTuple):
    start_sector: int
    end_sector: int
    size_bytes: int


class SystemFacts(NamedTuple):
    env: EnvFacts
    disk: DiskFacts
    partitions: Tuple[Partition, ...]
    boot_part: Optional[Partition]
    root_part: Optional[Partition]
    same_disk_boot_and_root: bool
    boot_disks: Tuple[str, ...]
    root_disks: Tuple[str, ...]
    existing_esp: Optional[Partition]
    existing_biosboot: Optional[Partition]
    free_regions: Tuple[FreeRegion, ...]
    tools: Dict[str, Optional[str]]
    packages: Dict[str, bool]


class PartSpec(NamedTuple):
    name: str
    size_bytes: int
    parttype_code: str  # sgdisk type code


class Check(NamedTuple):
    name: str
    status: str
    message: str


# --- Mutable planning / result types ------------------------------------------

class ConversionPlan(object):
    """What the later phases intend to do. Built up incrementally, hence mutable."""

    def __init__(self, disk_path):
        self.disk_path = disk_path
        self.convert_to_gpt = False
        self.create_biosboot = None   # Optional[PartSpec]
        self.create_esp = None        # Optional[PartSpec]
        self.esp_size_bytes = DEFAULT_ESP_SIZE_BYTES
        self.esp_mountpoint = "/boot/efi"
        self.packages_to_install = []
        self.needs_bios_grub_reinstall = False
        self.unified_config_steps = []

    def __repr__(self):
        return (
            "ConversionPlan(disk=%r, convert_to_gpt=%r, create_biosboot=%r, "
            "create_esp=%r, esp_size_bytes=%r, packages_to_install=%r)"
            % (
                self.disk_path,
                self.convert_to_gpt,
                self.create_biosboot,
                self.create_esp,
                self.esp_size_bytes,
                self.packages_to_install,
            )
        )


class ValidationResult(object):
    """Collected preflight checks."""

    def __init__(self):
        self.checks = []  # list of Check

    def add(self, name, status, message):
        self.checks.append(Check(name, status, message))

    @property
    def ok(self):
        return all(c.status != FAIL for c in self.checks)

    @property
    def failures(self):
        return [c for c in self.checks if c.status == FAIL]

    @property
    def warnings(self):
        return [c for c in self.checks if c.status == WARN]
