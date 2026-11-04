"""Pure parsers and fact assembly.

Every function here takes raw command output (strings) and returns structured
data. No subprocess calls, no filesystem access -- so it is all unit-testable
against captured fixtures.
"""
import json
import re
from typing import Dict, List, NamedTuple, Optional, Tuple

from .model import (
    GUID_BIOS_BOOT,
    GUID_ESP,
    DiskFacts,
    EnvFacts,
    FreeRegion,
    Partition,
    SystemFacts,
)


# --- RawInputs: the bundle a Probe hands to build_facts -----------------------

class RawInputs(NamedTuple):
    is_root: bool
    arch: str
    efi_present: bool
    os_release: str
    lsblk_json: str
    findmnt_json: str
    parted_free: str
    rpm_q: str
    which: Dict[str, Optional[str]]
    disk_override: Optional[str]


# --- Small helpers ------------------------------------------------------------

def _to_int(value, default=0):
    if value is None:
        return default
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _parse_sectors(token):
    """'2048s' -> 2048 ; '2048' -> 2048."""
    token = token.strip()
    if token.endswith("s"):
        token = token[:-1]
    return _to_int(token)


def _part_device(disk_path, number):
    """Compose a partition device path from a disk path and partition number.

    /dev/vda + 1 -> /dev/vda1 ; /dev/nvme0n1 + 1 -> /dev/nvme0n1p1
    """
    sep = "p" if disk_path and disk_path[-1].isdigit() else ""
    return "%s%s%d" % (disk_path, sep, number)


# --- os-release ---------------------------------------------------------------

def parse_os_release(text):
    """Return (os_id, version_major) from /etc/os-release content."""
    data = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip().strip('"').strip("'")
        data[key.strip()] = val
    os_id = data.get("ID", "")
    version_id = data.get("VERSION_ID", "")
    major = version_id.split(".")[0] if version_id else ""
    return os_id, major


# --- findmnt ------------------------------------------------------------------

def parse_findmnt(text):
    """Return {target: source} for all mounts from `findmnt -J` output."""
    result = {}
    doc = json.loads(text)

    def walk(nodes):
        for node in nodes or []:
            target = node.get("target")
            source = node.get("source")
            if target:
                result[target] = source
            walk(node.get("children"))

    walk(doc.get("filesystems"))
    return result


# --- lsblk --------------------------------------------------------------------

def parse_lsblk(text):
    """Flatten `lsblk -J -b` output into a list of normalized node dicts.

    Each node: name, path, type, size, fstype, uuid, parttype, mountpoint, pkname.
    Handles both the RHEL 8 "mountpoint" string and the RHEL 9+ "mountpoints"
    list forms.
    """
    doc = json.loads(text)
    nodes = []  # type: List[dict]

    def mount_of(item):
        mp = item.get("mountpoint")
        if mp is not None:
            return mp
        mps = item.get("mountpoints")
        if isinstance(mps, list):
            for m in mps:
                if m:
                    return m
        return None

    def walk(items, parent_name):
        for item in items or []:
            name = item.get("name")
            parttype = item.get("parttype")
            node = {
                "name": name,
                "path": name if (name or "").startswith("/") else "/dev/%s" % name,
                "type": item.get("type"),
                "size": _to_int(item.get("size")),
                "fstype": item.get("fstype"),
                "uuid": item.get("uuid"),
                "parttype": parttype.lower() if parttype else None,
                "mountpoint": mount_of(item),
                "pkname": item.get("pkname") or parent_name,
            }
            nodes.append(node)
            walk(item.get("children"), name)

    walk(doc.get("blockdevices"), None)
    return nodes


def _node_by_path(nodes, path):
    if not path:
        return None
    base = path.rsplit("/", 1)[-1]
    for node in nodes:
        if node["path"] == path or node["name"] == path or node["name"] == base:
            return node
    return None


def _node_by_name(nodes, name):
    if not name:
        return None
    for node in nodes:
        if node["name"] == name:
            return node
    return None


def _base_disk_node(nodes, node):
    """Walk pkname links upward until we reach a TYPE=disk node."""
    seen = set()
    cur = node
    while cur is not None:
        if cur.get("type") == "disk":
            return cur
        pk = cur.get("pkname")
        if not pk or pk in seen:
            break
        seen.add(pk)
        cur = _node_by_name(nodes, pk)
    return None


def _ancestor_partition(nodes, node):
    """Walk pkname links upward until we reach a TYPE=part node (or None)."""
    seen = set()
    cur = node
    while cur is not None:
        if cur.get("type") == "part":
            return cur
        pk = cur.get("pkname")
        if not pk or pk in seen:
            break
        seen.add(pk)
        cur = _node_by_name(nodes, pk)
    return None


# --- parted -------------------------------------------------------------------

class ParsedPart(NamedTuple):
    number: int
    start_sector: int
    end_sector: int
    size_sectors: int
    fs: str
    name: str
    flags: Tuple[str, ...]


class ParsedDisk(NamedTuple):
    path: str
    size_sectors: int
    sector_size: int
    pttype: str
    parts: Tuple[ParsedPart, ...]
    frees: Tuple[FreeRegion, ...]


class ParseError(Exception):
    """Raised when command output is not in the expected machine format."""


def parse_parted(text):
    """Parse `parted -m -s <disk> unit s print free` machine output.

    Raises ParseError if the output is not parted's `-m` machine format (for
    example a permission error or a missing `parted` binary), so callers can
    degrade gracefully instead of crashing.
    """
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if "BYT;" not in lines:
        snippet = (text or "").strip().splitlines()
        raise ParseError(
            "unrecognized parted output: %s"
            % (snippet[0] if snippet else "(empty)")
        )
    disk_line = None
    rows = []
    for line in lines:
        if line == "BYT;":
            continue
        if disk_line is None:
            disk_line = line
            continue
        rows.append(line)

    d = disk_line.rstrip(";").split(":")
    if len(d) < 6:
        raise ParseError("malformed parted disk line: %r" % disk_line)
    path = d[0]
    size_sectors = _parse_sectors(d[1])
    sector_size = _to_int(d[3], 512)
    pttype = d[5] if len(d) > 5 else ""

    parts = []
    frees = []
    for row in rows:
        f = row.rstrip(";").split(":")
        number = _to_int(f[0])
        start = _parse_sectors(f[1])
        end = _parse_sectors(f[2])
        size = _parse_sectors(f[3])
        fs = f[4] if len(f) > 4 else ""
        if fs == "free":
            frees.append(FreeRegion(start, end, size * sector_size))
        else:
            name = f[5] if len(f) > 5 else ""
            flagstr = f[6] if len(f) > 6 else ""
            flags = tuple(x.strip() for x in flagstr.split(",") if x.strip())
            parts.append(ParsedPart(number, start, end, size, fs, name, flags))

    return ParsedDisk(
        path, size_sectors, sector_size, _normalize_pttype(pttype),
        tuple(parts), tuple(frees),
    )


def _normalize_pttype(pttype):
    pttype = (pttype or "").strip().lower()
    if pttype == "msdos":
        return "dos"
    return pttype


# --- rpm ----------------------------------------------------------------------

_NOT_INSTALLED_RE = re.compile(r"package (\S+) is not installed")


def parse_rpm_q(text, packages):
    """Parse `rpm -q pkg1 pkg2 ...` output into {pkg: installed_bool}."""
    not_installed = set()
    installed = set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _NOT_INSTALLED_RE.match(line)
        if m:
            not_installed.add(m.group(1))
            continue
        for pkg in packages:
            if line.startswith(pkg + "-"):
                installed.add(pkg)
    return dict(
        (pkg, (pkg in installed) and (pkg not in not_installed))
        for pkg in packages
    )


# --- disk selection -----------------------------------------------------------

def select_primary_disk(lsblk_nodes, findmnt_map, override=None):
    """Pick the disk to convert: the one backing /boot (else /), or an override."""
    if override:
        return override
    for mount in ("/boot", "/"):
        src = findmnt_map.get(mount)
        node = _node_by_path(lsblk_nodes, src)
        if node is not None:
            disk = _base_disk_node(lsblk_nodes, node)
            if disk is not None:
                return disk["path"]
    # Last resort: the first TYPE=disk node.
    for node in lsblk_nodes:
        if node.get("type") == "disk":
            return node["path"]
    return None


# --- assembly -----------------------------------------------------------------

def build_facts(raw, packages):
    """Assemble SystemFacts from RawInputs. `packages` is the list to query."""
    os_id, major = parse_os_release(raw.os_release)
    env = EnvFacts(
        is_root=raw.is_root,
        arch=raw.arch,
        os_id=os_id,
        os_version_major=major,
        firmware_mode="uefi" if raw.efi_present else "bios",
    )

    lsblk_nodes = parse_lsblk(raw.lsblk_json)
    findmnt_map = parse_findmnt(raw.findmnt_json)
    disk_path = select_primary_disk(lsblk_nodes, findmnt_map, raw.disk_override)

    try:
        parsed = parse_parted(raw.parted_free)
    except ParseError:
        # Could not read the disk geometry (e.g. not root, or parted missing).
        # Produce degraded facts so validation reports clean failures.
        return _degraded_facts(env, disk_path, raw, packages)

    disk = DiskFacts(
        path=disk_path or parsed.path,
        size_bytes=parsed.size_sectors * parsed.sector_size,
        sector_size=parsed.sector_size,
        pttype=parsed.pttype,
    )

    # Merge parted geometry with lsblk identity, keyed by partition number.
    partitions = []
    by_device = {}
    for pp in parsed.parts:
        device = _part_device(disk.path, pp.number)
        node = _node_by_path(lsblk_nodes, device) or {}
        part = Partition(
            number=pp.number,
            device=device,
            start_sector=pp.start_sector,
            end_sector=pp.end_sector,
            size_bytes=pp.size_sectors * parsed.sector_size,
            parttype=node.get("parttype"),
            fstype=node.get("fstype"),
            fs_uuid=node.get("uuid"),
            mountpoint=node.get("mountpoint"),
            flags=pp.flags,
        )
        partitions.append(part)
        by_device[device] = part

    boot_part = _match_partition(by_device, findmnt_map.get("/boot"), mountpoint="/boot",
                                 partitions=partitions)

    # Root / same-disk detection via lsblk ancestry.
    root_part = None
    same_disk = False
    root_src = findmnt_map.get("/")
    root_node = _node_by_path(lsblk_nodes, root_src)
    if root_node is not None:
        root_disk = _base_disk_node(lsblk_nodes, root_node)
        same_disk = bool(root_disk and root_disk["path"] == disk.path)
        anc = _ancestor_partition(lsblk_nodes, root_node)
        if anc is not None:
            root_part = by_device.get(anc["path"])

    existing_esp = _find_esp(partitions)
    existing_biosboot = _find_biosboot(partitions)

    return SystemFacts(
        env=env,
        disk=disk,
        partitions=tuple(partitions),
        boot_part=boot_part,
        root_part=root_part,
        same_disk_boot_and_root=same_disk,
        existing_esp=existing_esp,
        existing_biosboot=existing_biosboot,
        free_regions=parsed.frees,
        tools=dict(raw.which),
        packages=parse_rpm_q(raw.rpm_q, packages),
    )


def _degraded_facts(env, disk_path, raw, packages):
    """Minimal facts when disk geometry is unreadable; validation will fail."""
    disk = DiskFacts(
        path=disk_path or "unknown",
        size_bytes=0,
        sector_size=512,
        pttype="unknown",
    )
    return SystemFacts(
        env=env,
        disk=disk,
        partitions=(),
        boot_part=None,
        root_part=None,
        same_disk_boot_and_root=False,
        existing_esp=None,
        existing_biosboot=None,
        free_regions=(),
        tools=dict(raw.which),
        packages=parse_rpm_q(raw.rpm_q, packages),
    )


def _match_partition(by_device, device, mountpoint, partitions):
    if device and device in by_device:
        return by_device[device]
    if mountpoint:
        for part in partitions:
            if part.mountpoint == mountpoint:
                return part
    return None


def _find_esp(partitions):
    for part in partitions:
        if part.parttype == GUID_ESP:
            return part
    for part in partitions:
        if part.fstype == "vfat" and part.mountpoint == "/boot/efi":
            return part
    return None


def _find_biosboot(partitions):
    for part in partitions:
        if part.parttype == GUID_BIOS_BOOT or "bios_grub" in part.flags:
            return part
    return None
