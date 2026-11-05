"""Tests for Phase 7 unified GRUB config."""
from franklin_bridge.plan import build_plan
from franklin_bridge.unified import (
    ETC_SYMLINK_TARGET,
    execute_unified_config,
    render_bootstrap_grubcfg,
)

from .support import FakeExecutor, make_facts


def test_render_bootstrap_grubcfg():
    out = render_bootstrap_grubcfg("b1d0fe98-1234", "/grub2")
    assert out == (
        "connectefi scsi\n"
        "search --no-floppy --fs-uuid --set=dev b1d0fe98-1234\n"
        "set prefix=($dev)/grub2\n"
        "export $prefix\n"
        "configfile $prefix/grub.cfg\n"
    )


def _run(fe):
    facts = make_facts()
    plan = build_plan(facts)
    return execute_unified_config(fe, facts, plan), fe


def test_grubenv_real_file_is_left_alone():
    fe = FakeExecutor(existing={"/boot/grub2/grubenv"})  # real file, not a link
    _run(fe)
    argvs = [c[1] for c in fe.calls_of("run")]
    assert not any(a and a[0] == "grub2-editenv" for a in argvs)


def test_grubenv_symlink_is_replaced_with_real_file():
    fe = FakeExecutor(links={"/boot/grub2/grubenv": "../efi/EFI/redhat/grubenv"})
    _run(fe)
    argvs = [c[1] for c in fe.calls_of("run")]
    assert ("rm", "-f", "/boot/grub2/grubenv") in argvs
    assert ("grub2-editenv", "/boot/grub2/grubenv", "create") in argvs


def test_generates_real_config_and_bootstrap():
    fe = FakeExecutor(
        existing={"/boot/grub2/grubenv"},
        boot_uuid="b1d0fe98-aaaa", grub_dir="/grub2",
    )
    summary, fe = _run(fe)
    argvs = [c[1] for c in fe.calls_of("run")]
    assert ("grub2-mkconfig", "-o", "/boot/grub2/grub.cfg") in argvs

    # Bootstrap config written to the ESP with values from grub2-probe/mkrelpath.
    writes = {c[1]: c[2] for c in fe.calls_of("write_text")}
    bootstrap = writes["/boot/efi/EFI/redhat/grub.cfg"]
    assert "search --no-floppy --fs-uuid --set=dev b1d0fe98-aaaa" in bootstrap
    assert "set prefix=($dev)/grub2" in bootstrap
    assert summary["boot_uuid"] == "b1d0fe98-aaaa"


def test_etc_symlinks_created_and_repointed():
    # /etc/grub2.cfg already correct; /etc/grub2-efi.cfg points at the EFI path.
    fe = FakeExecutor(
        existing={"/boot/grub2/grubenv"},
        links={
            "/etc/grub2.cfg": ETC_SYMLINK_TARGET,
            "/etc/grub2-efi.cfg": "../boot/efi/EFI/redhat/grub.cfg",
        },
    )
    _run(fe)
    argvs = [c[1] for c in fe.calls_of("run")]
    # Already-correct one is left alone.
    assert ("rm", "-f", "/etc/grub2.cfg") not in argvs
    assert ("ln", "-s", ETC_SYMLINK_TARGET, "/etc/grub2.cfg") not in argvs
    # The mispointed one is removed and recreated.
    assert ("rm", "-f", "/etc/grub2-efi.cfg") in argvs
    assert ("ln", "-s", ETC_SYMLINK_TARGET, "/etc/grub2-efi.cfg") in argvs


def test_removes_grubenv_rpmnew_if_present():
    fe = FakeExecutor(existing={"/boot/grub2/grubenv",
                                "/boot/grub2/grubenv.rpmnew"})
    _run(fe)
    argvs = [c[1] for c in fe.calls_of("run")]
    assert ("rm", "-f", "/boot/grub2/grubenv.rpmnew") in argvs


def test_dry_run_uses_placeholders(tmp_path):
    from franklin_bridge.executor import Executor

    logs = []
    ex = Executor(dry_run=True, log=logs.append)
    facts = make_facts()
    plan = build_plan(facts)
    summary = execute_unified_config(ex, facts, plan)
    assert summary["boot_uuid"] == "<boot-fs-uuid>"
    assert any("would run: grub2-mkconfig" in m for m in logs)
    assert any("would write file: /boot/efi/EFI/redhat/grub.cfg" in m
               for m in logs)
