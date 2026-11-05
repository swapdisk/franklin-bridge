"""Shared test helpers: fixture loading and a baseline SystemFacts builder."""
import os

from franklin_bridge.inventory import RawInputs
from franklin_bridge.model import (
    ESSENTIAL_TOOLS,
    EFI_PACKAGES,
    GIB,
    MIB,
    DiskFacts,
    EnvFacts,
    FreeRegion,
    Partition,
    SystemFacts,
)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture_path(scenario, name):
    return os.path.join(FIXTURES, scenario, name)


def read_fixture(scenario, name):
    with open(fixture_path(scenario, name), "r") as fh:
        return fh.read()


def load_raw(scenario, is_root=True, arch="x86_64", efi_present=False,
             which=None, disk_override=None):
    """Build RawInputs from a fixture directory, with env fields overridable."""
    if which is None:
        which = dict((t, "/usr/sbin/%s" % t) for t in ESSENTIAL_TOOLS)
    return RawInputs(
        is_root=is_root,
        arch=arch,
        efi_present=efi_present,
        os_release=read_fixture(scenario, "os-release"),
        lsblk_json=read_fixture(scenario, "lsblk.json"),
        findmnt_json=read_fixture(scenario, "findmnt.json"),
        parted_free=read_fixture(scenario, "parted-free.txt"),
        rpm_q=read_fixture(scenario, "rpm-q.txt"),
        which=which,
        disk_override=disk_override,
    )


class FakeExecutor(object):
    """Records actions instead of performing them; for testing phase logic."""

    def __init__(self, existing=(), files=None, dir_entries=None,
                 uuid="ABCD-1234", mounted=(), dev_fstype="",
                 links=None, grub_dir="/grub2", boot_uuid=None, dump_text=""):
        self.dry_run = False
        self.existing = set(existing)
        self.files = dict(files or {})
        self.dir_entries = dict(dir_entries or {})
        self.uuid = uuid
        self.mounted = set(mounted)
        self.dev_fstype = dev_fstype
        self.links = dict(links or {})  # path -> symlink target
        self.grub_dir = grub_dir
        self.boot_uuid = boot_uuid if boot_uuid is not None else uuid
        self.dump_text = dump_text  # returned for `sfdisk -d`
        self.calls = []  # list of tuples describing each action

    def log(self, msg):
        self.calls.append(("log", msg))

    def run(self, argv, mutates=True, check=True, capture_to=None):
        self.calls.append(("run", tuple(argv), capture_to))
        return 0

    def run_input(self, argv, input_text, mutates=True, check=True):
        self.calls.append(("run_input", tuple(argv), input_text))
        return 0

    def makedirs(self, path):
        self.calls.append(("makedirs", path))

    def write_text(self, path, text):
        self.calls.append(("write_text", path, text))
        self.files[path] = text

    def copy(self, src, dst):
        self.calls.append(("copy", src, dst))

    def capture(self, argv, check=True, default=""):
        self.calls.append(("capture", tuple(argv)))
        if "sfdisk" in argv and "-d" in argv:
            return self.dump_text
        if "TYPE" in argv:
            return self.dev_fstype + "\n"
        if "grub2-mkrelpath" in argv:
            return self.grub_dir + "\n"
        if "grub2-probe" in argv:
            return self.boot_uuid + "\n"
        return self.uuid + "\n"

    def append_text(self, path, text):
        self.calls.append(("append_text", path, text))
        self.files[path] = self.files.get(path, "") + text

    def read_text(self, path):
        return self.files.get(path, "")

    def exists(self, path):
        return path in self.existing

    def islink(self, path):
        return path in self.links

    def readlink(self, path):
        return self.links.get(path)

    def ismount(self, path):
        return path in self.mounted

    def listdir(self, path):
        return list(self.dir_entries.get(path, []))

    def calls_of(self, kind):
        return [c for c in self.calls if c[0] == kind]


def _baseline_packages():
    pkgs = dict((p, False) for p in EFI_PACKAGES)
    pkgs["grub2-pc"] = True
    return pkgs


def make_facts(**overrides):
    """A healthy baseline SystemFacts (RHEL 8, BIOS, DOS, free at end).

    Override top-level SystemFacts fields via keyword args. For nested records,
    use NamedTuple._replace in the test, e.g.:
        f = make_facts()
        f = f._replace(env=f.env._replace(firmware_mode="uefi"))
    """
    env = EnvFacts(is_root=True, arch="x86_64", os_id="rhel",
                   os_version_major="8", firmware_mode="bios")
    disk = DiskFacts(path="/dev/vda", size_bytes=20 * GIB,
                     sector_size=512, pttype="dos")
    boot = Partition(1, "/dev/vda1", 2048, 2099199, 1 * GIB, "0x83",
                     "xfs", "boot-uuid-1111", "/boot", ())
    root = Partition(2, "/dev/vda2", 2099200, 37750783, 17 * GIB, "0x8e",
                     "LVM2_member", "pv-uuid-2222", None, ())
    disk_sectors = disk.size_bytes // disk.sector_size
    free = (FreeRegion(37750784, disk_sectors - 1, 2 * GIB),)

    base = SystemFacts(
        env=env,
        disk=disk,
        partitions=(boot, root),
        boot_part=boot,
        root_part=root,
        same_disk_boot_and_root=True,
        boot_disks=("/dev/vda",),
        root_disks=("/dev/vda",),
        existing_esp=None,
        existing_biosboot=None,
        free_regions=free,
        tools=dict((t, "/usr/sbin/%s" % t) for t in ESSENTIAL_TOOLS),
        # Realistic BIOS baseline: grub2-pc is installed, the EFI packages aren't.
        packages=_baseline_packages(),
        dos_extended_present=False,
        dos_unsupported_types=(),
    )
    if overrides:
        base = base._replace(**overrides)
    return base
