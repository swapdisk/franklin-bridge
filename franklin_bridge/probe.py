"""Impure collectors: run real commands and return raw output as RawInputs.

This is the only module in the preflight path that touches the system, so it is
deliberately thin and is exercised by the VM harness rather than unit tests.
"""
import os
import platform
import shutil
import subprocess

from .inventory import RawInputs, parse_findmnt, parse_lsblk, select_primary_disk
from .model import ESSENTIAL_TOOLS, EFI_PACKAGES


def _run(cmd, allow_fail=False):
    # Capture stdout only; discard stderr. Tools like parted print warnings to
    # stderr (e.g. "Not all of the space ... appears to be used" after a disk
    # grow), and merging those into stdout would corrupt the machine-readable
    # output we parse.
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError) as exc:
        if allow_fail and isinstance(exc, subprocess.CalledProcessError):
            return exc.output.decode("utf-8", "replace") if exc.output else ""
        if allow_fail:
            return ""
        raise
    return out.decode("utf-8", "replace")


def _read_file(path):
    try:
        with open(path, "r") as fh:
            return fh.read()
    except OSError:
        return ""


class Probe(object):
    """Collects raw system facts. Swap for a fake in tests."""

    LSBLK_COLUMNS = "NAME,KNAME,TYPE,SIZE,FSTYPE,UUID,PARTTYPE,MOUNTPOINT,PKNAME"

    def collect(self, disk_override=None):
        is_root = os.geteuid() == 0
        arch = platform.machine()
        efi_present = os.path.isdir("/sys/firmware/efi")
        os_release = _read_file("/etc/os-release")

        lsblk_json = _run(["lsblk", "-J", "-b", "-o", self.LSBLK_COLUMNS])
        findmnt_json = _run(["findmnt", "-J", "-o", "TARGET,SOURCE"])
        rpm_q = _run(["rpm", "-q"] + list(EFI_PACKAGES), allow_fail=True)
        which = dict((t, shutil.which(t)) for t in ESSENTIAL_TOOLS)

        disk = disk_override or self._preselect_disk(lsblk_json, findmnt_json)
        parted_free = ""
        if disk:
            parted_free = _run(
                ["parted", "-m", "-s", disk, "unit", "s", "print", "free"],
                allow_fail=True,
            )

        return RawInputs(
            is_root=is_root,
            arch=arch,
            efi_present=efi_present,
            os_release=os_release,
            lsblk_json=lsblk_json,
            findmnt_json=findmnt_json,
            parted_free=parted_free,
            rpm_q=rpm_q,
            which=which,
            disk_override=disk_override,
        )

    @staticmethod
    def _preselect_disk(lsblk_json, findmnt_json):
        try:
            nodes = parse_lsblk(lsblk_json)
            mounts = parse_findmnt(findmnt_json)
        except (ValueError, KeyError):
            return None
        return select_primary_disk(nodes, mounts, None)
