"""Tests for the execution layer."""
import os

from franklin_bridge.executor import Executor


def test_executor_performs_fs_actions(tmp_path):
    logs = []
    ex = Executor(dry_run=False, log=logs.append)

    d = os.path.join(str(tmp_path), "sub", "dir")
    ex.makedirs(d)
    assert os.path.isdir(d)

    f = os.path.join(d, "note.txt")
    ex.write_text(f, "hello")
    with open(f) as fh:
        assert fh.read() == "hello"

    dst = os.path.join(d, "note-copy.txt")
    ex.copy(f, dst)
    with open(dst) as fh:
        assert fh.read() == "hello"


def test_executor_dry_run_skips_mutations(tmp_path):
    logs = []
    ex = Executor(dry_run=True, log=logs.append)

    d = os.path.join(str(tmp_path), "sub")
    ex.makedirs(d)
    ex.write_text(os.path.join(d, "x.txt"), "data")

    assert not os.path.exists(d)
    assert any("would create directory" in m for m in logs)
    assert any("would write file" in m for m in logs)


def test_executor_run_capture_to(tmp_path):
    out = os.path.join(str(tmp_path), "echoed.txt")
    ex = Executor(dry_run=False, log=lambda m: None)
    ex.run(["printf", "abc"], capture_to=out)
    with open(out) as fh:
        assert fh.read() == "abc"


def test_executor_dry_run_skips_command(tmp_path):
    out = os.path.join(str(tmp_path), "should-not-exist.txt")
    logs = []
    ex = Executor(dry_run=True, log=logs.append)
    ex.run(["printf", "abc"], capture_to=out)
    assert not os.path.exists(out)
    assert any("would run" in m for m in logs)
