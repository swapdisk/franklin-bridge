"""Tests for Phase 3 partition surgery planning and execution."""
import pytest

from franklin_bridge.inventory import build_facts
from franklin_bridge.model import EFI_PACKAGES, MIB
from franklin_bridge.partition import (
    execute_partitioning,
    plan_partition_commands,
)
from franklin_bridge.plan import build_plan

from .support import FakeExecutor, load_raw, make_facts


def _argv_for(steps, prog_first_arg):
    """Return the argv of the step whose command matches (sgdisk flag etc.)."""
    out = []
    for s in steps:
        if prog_first_arg in s.argv:
            out.append(s.argv)
    return out


def test_plan_standard_converts_and_creates_two():
    facts = make_facts()
    plan = build_plan(facts)
    steps, new_parts = plan_partition_commands(facts, plan)

    # First step is the GPT conversion.
    assert steps[0].argv == ["sgdisk", "-g", "/dev/vda"]

    # New partitions are numbered after the existing two.
    assert new_parts == [(3, "biosboot"), (4, "esp")]

    # BIOS Boot: 1 MiB -> 2048 sectors, type ef02.
    bios = steps[1].argv
    assert "-n" in bios and "3:0:+2048" in bios
    assert "3:ef02" in bios

    # ESP: default 200 MiB -> 409600 sectors, type ef00.
    esp = steps[2].argv
    assert "4:0:+409600" in esp
    assert "4:ef00" in esp


def test_plan_custom_esp_size_sectors():
    facts = make_facts()
    plan = build_plan(facts, esp_size_bytes=512 * MIB)
    steps, _ = plan_partition_commands(facts, plan)
    esp = steps[-1].argv
    assert "4:0:+%d" % (512 * MIB // 512) in esp  # 1048576 sectors


def test_plan_resume_when_already_gpt_does_nothing():
    facts = build_facts(load_raw("gpt_converted"), EFI_PACKAGES)
    plan = build_plan(facts)
    steps, new_parts = plan_partition_commands(facts, plan)
    assert steps == []
    assert new_parts == []


def test_execute_runs_sgdisk_then_partx_then_verifies():
    facts = make_facts()
    plan = build_plan(facts)
    # The new device nodes "exist" after partx in this fake.
    fe = FakeExecutor(existing={"/dev/vda3", "/dev/vda4"})

    summary = execute_partitioning(fe, facts, plan)

    runs = [c for c in fe.calls if c[0] == "run"]
    argvs = [c[1] for c in runs]
    assert ("sgdisk", "-g", "/dev/vda") in argvs
    # partx -a for each new partition number.
    assert ("partx", "-a", "--nr", "3", "/dev/vda") in argvs
    assert ("partx", "-a", "--nr", "4", "/dev/vda") in argvs
    assert summary["new_parts"] == [(3, "biosboot"), (4, "esp")]
    assert set(summary["verified"]) == {"/dev/vda3", "/dev/vda4"}


def test_execute_raises_if_new_partition_missing():
    facts = make_facts()
    plan = build_plan(facts)
    fe = FakeExecutor(existing=set())  # partx "succeeds" but device never appears
    with pytest.raises(RuntimeError):
        execute_partitioning(fe, facts, plan)


def test_execute_dry_run_skips_everything(tmp_path):
    from franklin_bridge.executor import Executor

    logs = []
    ex = Executor(dry_run=True, log=logs.append)
    facts = make_facts()
    plan = build_plan(facts)
    summary = execute_partitioning(ex, facts, plan)

    # Nothing verified in dry-run; commands only logged.
    assert summary["verified"] == []
    assert any("would run: sgdisk -g" in m for m in logs)
    assert any("would run: partx -a --nr 3" in m for m in logs)
