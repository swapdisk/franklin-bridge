"""Tests for refusing unsupported MBR layouts (extended/logical, unknown types)."""
from franklin_bridge.inventory import dos_type_signals, parse_lsblk
from franklin_bridge.model import FAIL, PASS
from franklin_bridge.plan import build_plan
from franklin_bridge.validate import validate

from .support import make_facts

STANDARD = """
{"blockdevices":[
 {"name":"vda","type":"disk","pkname":null,"children":[
   {"name":"vda1","type":"part","parttype":"0x83","mountpoint":"/boot","pkname":"vda"},
   {"name":"vda2","type":"part","parttype":"0x8e","pkname":"vda"}
 ]}
]}
"""

EXTENDED = """
{"blockdevices":[
 {"name":"vda","type":"disk","pkname":null,"children":[
   {"name":"vda1","type":"part","parttype":"0x83","mountpoint":"/boot","pkname":"vda"},
   {"name":"vda2","type":"part","parttype":"0x5","pkname":"vda","children":[
     {"name":"vda5","type":"part","parttype":"0x8e","pkname":"vda2"}
   ]}
 ]}
]}
"""

NTFS = """
{"blockdevices":[
 {"name":"vda","type":"disk","pkname":null,"children":[
   {"name":"vda1","type":"part","parttype":"0x7","pkname":"vda"},
   {"name":"vda2","type":"part","parttype":"0x8e","pkname":"vda"}
 ]}
]}
"""


def test_dos_type_signals_standard_ok():
    extended, unsupported = dos_type_signals(parse_lsblk(STANDARD), "/dev/vda")
    assert extended is False
    assert unsupported == ()


def test_dos_type_signals_detects_extended():
    extended, unsupported = dos_type_signals(parse_lsblk(EXTENDED), "/dev/vda")
    assert extended is True


def test_dos_type_signals_detects_unknown_type():
    extended, unsupported = dos_type_signals(parse_lsblk(NTFS), "/dev/vda")
    assert extended is False
    assert unsupported == ("0x7",)


def _status(result, name):
    for c in result.checks:
        if c.name == name:
            return c.status
    raise AssertionError("no check named %r" % name)


def test_validate_healthy_layout_passes():
    result = validate(make_facts(), build_plan(make_facts()))
    assert _status(result, "partition_layout") == PASS
    assert _status(result, "partition_types") == PASS


def test_validate_extended_partition_fails():
    facts = make_facts(dos_extended_present=True)
    result = validate(facts, build_plan(facts))
    assert _status(result, "partition_layout") == FAIL
    assert not result.ok


def test_validate_unsupported_type_fails():
    facts = make_facts(dos_unsupported_types=("0x7",))
    result = validate(facts, build_plan(facts))
    assert _status(result, "partition_types") == FAIL
    assert "0x7" in [c.message for c in result.checks
                     if c.name == "partition_types"][0]
    assert not result.ok
