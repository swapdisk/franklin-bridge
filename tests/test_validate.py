"""Unit tests for validate (pure). Edge cases built via make_facts()._replace."""
from franklin_bridge.model import (
    ESSENTIAL_TOOLS,
    EFI_PACKAGES,
    FAIL,
    GIB,
    PASS,
    WARN,
    FreeRegion,
)
from franklin_bridge.plan import build_plan
from franklin_bridge.validate import validate

from .support import make_facts


def _run(facts):
    plan = build_plan(facts)
    return validate(facts, plan)


def _status(result, name):
    for c in result.checks:
        if c.name == name:
            return c.status
    raise AssertionError("no check named %r" % name)


def test_healthy_system_passes():
    result = _run(make_facts())
    assert result.ok
    assert _status(result, "root") == PASS
    assert _status(result, "firmware") == PASS
    assert _status(result, "partition_table") == PASS
    assert _status(result, "free_space") == PASS
    # packages missing -> warn, but still ok overall
    assert _status(result, "packages") == WARN


def test_not_root_fails():
    f = make_facts()
    f = f._replace(env=f.env._replace(is_root=False))
    result = _run(f)
    assert not result.ok
    assert _status(result, "root") == FAIL


def test_wrong_arch_fails():
    f = make_facts()
    f = f._replace(env=f.env._replace(arch="aarch64"))
    assert _status(_run(f), "arch") == FAIL


def test_unsupported_os_fails():
    f = make_facts()
    f = f._replace(env=f.env._replace(os_version_major="7"))
    assert _status(_run(f), "os") == FAIL


def test_uefi_firmware_fails():
    f = make_facts()
    f = f._replace(env=f.env._replace(firmware_mode="uefi"))
    assert _status(_run(f), "firmware") == FAIL


def test_already_gpt_warns_but_ok():
    f = make_facts()
    f = f._replace(disk=f.disk._replace(pttype="gpt"))
    result = _run(f)
    assert _status(result, "partition_table") == WARN
    assert result.ok  # warning does not fail preflight


def test_no_separate_boot_fails():
    result = _run(make_facts(boot_part=None))
    assert _status(result, "boot_partition") == FAIL


def test_boot_and_root_different_disks_fails():
    result = _run(make_facts(same_disk_boot_and_root=False))
    assert _status(result, "single_disk") == FAIL


def test_missing_tool_fails():
    tools = dict((t, "/usr/sbin/%s" % t) for t in ESSENTIAL_TOOLS)
    tools["sgdisk"] = None
    result = _run(make_facts(tools=tools))
    assert _status(result, "tools") == FAIL


def test_all_packages_present_passes_packages_check():
    f = make_facts(packages={p: True for p in EFI_PACKAGES})
    assert _status(_run(f), "packages") == PASS


def test_no_free_space_fails():
    result = _run(make_facts(free_regions=()))
    assert _status(result, "free_space") == FAIL


def test_free_space_not_at_end_fails():
    # Plenty of total free space, but it is in the middle of the disk.
    midfree = (FreeRegion(3_000_000, 5_000_000, 1 * GIB),)
    result = _run(make_facts(free_regions=midfree))
    assert _status(result, "free_space") == FAIL
