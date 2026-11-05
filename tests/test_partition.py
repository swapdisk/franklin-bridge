"""Tests for Phase 3 partition surgery (sfdisk-based)."""
import pytest

from franklin_bridge.inventory import build_facts
from franklin_bridge.model import EFI_PACKAGES, GUID_BIOS_BOOT, GUID_ESP, MIB
from franklin_bridge.partition import (
    append_line,
    build_gpt_script,
    execute_partitioning,
    planned_new_partitions,
)
from franklin_bridge.plan import build_plan

from .support import FakeExecutor, load_raw, make_facts

DOS_DUMP = (
    "label: dos\n"
    "label-id: 0xa17016f2\n"
    "device: /dev/vda\n"
    "unit: sectors\n"
    "\n"
    "/dev/vda1 : start=        2048, size=     2097152, type=83, bootable\n"
    "/dev/vda2 : start=     2099200, size=    39843840, type=8e\n"
)


def test_planned_new_partitions_numbers_after_existing():
    facts = make_facts()  # partitions 1 and 2
    plan = build_plan(facts)
    assert planned_new_partitions(facts, plan) == [(3, "biosboot"), (4, "esp")]


def test_build_gpt_script_preserves_and_translates():
    facts = make_facts()
    plan = build_plan(facts)
    specs = [plan.create_biosboot, plan.create_esp]
    script = build_gpt_script(DOS_DUMP, specs, 512)

    assert script.startswith("label: gpt")
    # Existing partitions preserved at identical start/size, types -> GUIDs.
    assert "start=2048, size=2097152, type=0fc63daf-8483-4772-8e79-3d69d8477de4" in script
    assert "start=2099200, size=39843840, type=e6d6d379-f507-44c2-a23c-238f2a3df928" in script
    # New partitions: BIOS Boot (1 MiB = 2048 sectors) and ESP (200 MiB).
    assert 'size=2048, type=%s, name="BIOS boot partition"' % GUID_BIOS_BOOT in script
    assert 'size=%d, type=%s, name="EFI System Partition"' % (200 * MIB // 512, GUID_ESP) in script


def test_build_gpt_script_rejects_unknown_type():
    bad_dump = "/dev/vda1 : start=2048, size=2097152, type=07\n"  # NTFS
    with pytest.raises(ValueError):
        build_gpt_script(bad_dump, [], 512)


def test_append_line():
    facts = make_facts()
    plan = build_plan(facts)
    line = append_line(plan.create_esp, 512)
    assert line == 'size=%d, type=%s, name="EFI System Partition"\n' % (
        200 * MIB // 512, GUID_ESP)


def test_execute_convert_path_runs_sfdisk_and_verifies():
    facts = make_facts()  # DOS -> convert
    plan = build_plan(facts)
    fe = FakeExecutor(existing={"/dev/vda3", "/dev/vda4"})
    # Make the pre- and post-conversion dumps match so verification passes.
    fe.dump_text = DOS_DUMP
    summary = execute_partitioning(fe, facts, plan)

    # The conversion wrote a GPT script via stdin, not sgdisk.
    inputs = [c for c in fe.calls if c[0] == "run_input"]
    assert any(c[1] == ("sfdisk", "--no-reread", "/dev/vda") for c in inputs)
    runs = [c[1] for c in fe.calls if c[0] == "run"]
    assert ("partx", "-a", "--nr", "3", "/dev/vda") in runs
    assert ("partx", "-a", "--nr", "4", "/dev/vda") in runs
    assert summary["converted"] is True
    assert set(summary["verified"]) == {"/dev/vda3", "/dev/vda4"}


def test_execute_resume_appends_only_missing():
    facts = build_facts(load_raw("gpt_converted"), EFI_PACKAGES)
    plan = build_plan(facts)  # already GPT, esp+biosboot exist -> nothing to do
    fe = FakeExecutor()
    summary = execute_partitioning(fe, facts, plan)
    assert summary["converted"] is False
    assert summary["new_parts"] == []
    assert not any(c[0] == "run_input" for c in fe.calls)


def test_execute_raises_if_new_partition_missing():
    facts = make_facts()
    plan = build_plan(facts)
    fe = FakeExecutor(existing=set())  # devices never appear
    fe.dump_text = DOS_DUMP
    with pytest.raises(RuntimeError):
        execute_partitioning(fe, facts, plan)


def test_execute_dry_run_skips_everything():
    from franklin_bridge.executor import Executor

    logs = []
    ex = Executor(dry_run=True, log=logs.append)
    facts = make_facts()
    plan = build_plan(facts)
    summary = execute_partitioning(ex, facts, plan)
    assert summary["verified"] == []
    assert any("would run: sfdisk -d /dev/vda" in m for m in logs)
