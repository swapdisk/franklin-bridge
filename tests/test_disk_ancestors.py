"""Tests for full-graph disk-ancestor resolution (nested + multi-disk layouts)."""
from franklin_bridge.inventory import build_facts, disk_ancestors, parse_lsblk
from franklin_bridge.model import EFI_PACKAGES, FAIL
from franklin_bridge.plan import build_plan
from franklin_bridge.validate import validate

from .support import load_raw, make_facts

# Single-disk LUKS -> LVM: vda -> vda2(crypt dm-0) -> root(dm-1)
LUKS_JSON = """
{"blockdevices":[
 {"name":"vda","kname":"vda","type":"disk","pkname":null,"children":[
   {"name":"vda1","kname":"vda1","type":"part","mountpoint":"/boot","pkname":"vda"},
   {"name":"vda2","kname":"vda2","type":"part","fstype":"crypto_LUKS","pkname":"vda","children":[
     {"name":"luks-x","kname":"dm-0","type":"crypt","pkname":"vda2","children":[
       {"name":"rhel-root","kname":"dm-1","type":"lvm","mountpoint":"/","pkname":"dm-0"}
     ]}
   ]}
 ]}
]}
"""

# md RAID1 root across TWO disks: md127 has parents vda2 and vdb2.
MD_RAID_JSON = """
{"blockdevices":[
 {"name":"vda","kname":"vda","type":"disk","pkname":null,"children":[
   {"name":"vda1","kname":"vda1","type":"part","mountpoint":"/boot","pkname":"vda"},
   {"name":"vda2","kname":"vda2","type":"part","fstype":"linux_raid_member","pkname":"vda","children":[
     {"name":"md127","kname":"md127","type":"raid1","mountpoint":"/","pkname":"vda2"}
   ]}
 ]},
 {"name":"vdb","kname":"vdb","type":"disk","pkname":null,"children":[
   {"name":"vdb2","kname":"vdb2","type":"part","fstype":"linux_raid_member","pkname":"vdb","children":[
     {"name":"md127","kname":"md127","type":"raid1","mountpoint":"/","pkname":"vdb2"}
   ]}
 ]}
]}
"""


def test_disk_ancestors_luks_single_disk():
    nodes = parse_lsblk(LUKS_JSON)
    assert disk_ancestors(nodes, "/dev/mapper/rhel-root") == {"/dev/vda"}
    assert disk_ancestors(nodes, "/dev/vda1") == {"/dev/vda"}


def test_disk_ancestors_md_spans_two_disks():
    nodes = parse_lsblk(MD_RAID_JSON)
    # Root on md127 must resolve to BOTH underlying disks.
    assert disk_ancestors(nodes, "/dev/md127") == {"/dev/vda", "/dev/vdb"}


def test_luks_layout_passes_preflight():
    facts = build_facts(load_raw("rhel8_luks_lvm"), EFI_PACKAGES)
    assert facts.disk.path == "/dev/vda"
    assert facts.boot_disks == ("/dev/vda",)
    assert facts.root_disks == ("/dev/vda",)
    assert facts.same_disk_boot_and_root is True
    assert facts.root_part is not None and facts.root_part.device == "/dev/vda2"
    result = validate(facts, build_plan(facts))
    assert result.ok, [c for c in result.checks if c.status == FAIL]


def test_multi_disk_root_fails_with_clear_message():
    facts = make_facts(
        same_disk_boot_and_root=False,
        boot_disks=("/dev/vda",),
        root_disks=("/dev/vda", "/dev/vdb"),
    )
    result = validate(facts, build_plan(facts))
    sd = [c for c in result.checks if c.name == "single_disk"][0]
    assert sd.status == FAIL
    assert "multiple disks" in sd.message
    assert "/dev/vdb" in sd.message
    assert not result.ok
