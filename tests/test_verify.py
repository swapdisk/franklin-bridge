"""Tests for Phase 8 end-state validation."""
from franklin_bridge.inventory import build_facts
from franklin_bridge.model import EFI_PACKAGES
from franklin_bridge.plan import build_plan
from franklin_bridge.unified import ETC_SYMLINK_TARGET
from franklin_bridge.verify import (
    EndStateObs,
    check_end_state,
    execute_validation,
    gather_end_state,
)

from .support import FakeExecutor, load_raw

BOOT_UUID = "boot-uuid-1111"  # from the gpt_converted fixture (vda3 /boot)

GOOD_BOOTSTRAP = (
    "connectefi scsi\n"
    "search --no-floppy --fs-uuid --set=dev %s\n"
    "set prefix=($dev)/grub2\n"
    "export $prefix\n"
    "configfile $prefix/grub.cfg\n" % BOOT_UUID
)


def _good_obs(**over):
    base = dict(
        grubx64=True, shimx64=True, fallback=True,
        bootstrap_text=GOOD_BOOTSTRAP, real_cfg=True,
        grubenv_exists=True, grubenv_islink=False,
        etc_grub2_target=ETC_SYMLINK_TARGET,
        etc_grub2efi_target=ETC_SYMLINK_TARGET,
        i386pc_module=True, fstab_has_esp=True,
    )
    base.update(over)
    return EndStateObs(**base)


def _gpt_facts():
    return build_facts(load_raw("gpt_converted"), EFI_PACKAGES)


def _status(result, name):
    for c in result.checks:
        if c.name == name:
            return c.status
    raise AssertionError("no check named %r" % name)


def test_fully_converted_system_passes():
    result = check_end_state(_gpt_facts(), _good_obs(), BOOT_UUID)
    assert result.ok, [c for c in result.checks if c.status != "pass"]


def test_detects_not_gpt():
    facts = _gpt_facts()._replace(
        disk=_gpt_facts().disk._replace(pttype="dos"))
    result = check_end_state(facts, _good_obs(), BOOT_UUID)
    assert _status(result, "gpt") == "fail"
    assert not result.ok


def test_detects_unpopulated_esp():
    result = check_end_state(_gpt_facts(), _good_obs(grubx64=False), BOOT_UUID)
    assert _status(result, "esp_populated") == "fail"


def test_detects_missing_fallback():
    result = check_end_state(_gpt_facts(), _good_obs(fallback=False), BOOT_UUID)
    assert _status(result, "uefi_fallback") == "fail"


def test_detects_bad_bootstrap():
    result = check_end_state(_gpt_facts(),
                             _good_obs(bootstrap_text="garbage"), BOOT_UUID)
    assert _status(result, "bootstrap_config") == "fail"


def test_detects_grubenv_symlink():
    result = check_end_state(_gpt_facts(), _good_obs(grubenv_islink=True),
                             BOOT_UUID)
    assert _status(result, "grubenv_real") == "fail"


def test_detects_bad_symlinks():
    result = check_end_state(
        _gpt_facts(),
        _good_obs(etc_grub2efi_target="../boot/efi/EFI/redhat/grub.cfg"),
        BOOT_UUID)
    assert _status(result, "etc_symlinks") == "fail"


def test_gather_end_state_reads_live_system():
    fe = FakeExecutor(
        existing={
            "/boot/efi/EFI/redhat/grubx64.efi",
            "/boot/efi/EFI/redhat/shimx64.efi",
            "/boot/efi/EFI/BOOT/BOOTX64.EFI",
            "/boot/grub2/grub.cfg",
            "/boot/grub2/grubenv",
            "/boot/grub2/i386-pc/normal.mod",
        },
        files={
            "/boot/efi/EFI/redhat/grub.cfg": GOOD_BOOTSTRAP,
            "/etc/fstab": "UUID=x /boot/efi vfat umask=0077 0 2\n",
        },
        links={
            "/etc/grub2.cfg": ETC_SYMLINK_TARGET,
            "/etc/grub2-efi.cfg": ETC_SYMLINK_TARGET,
        },
    )
    plan = build_plan(_gpt_facts())
    obs = gather_end_state(fe, plan)
    assert obs.grubx64 and obs.shimx64 and obs.fallback
    assert obs.fstab_has_esp is True
    assert obs.grubenv_islink is False
    assert obs.etc_grub2_target == ETC_SYMLINK_TARGET


def test_execute_validation_dry_run_returns_none():
    from franklin_bridge.executor import Executor
    ex = Executor(dry_run=True, log=lambda m: None)
    assert execute_validation(ex, _gpt_facts(), build_plan(_gpt_facts())) is None


def test_execute_validation_with_injected_reprobe():
    facts = _gpt_facts()
    fe = FakeExecutor(
        existing={
            "/boot/efi/EFI/redhat/grubx64.efi",
            "/boot/efi/EFI/redhat/shimx64.efi",
            "/boot/efi/EFI/BOOT/BOOTX64.EFI",
            "/boot/grub2/grub.cfg", "/boot/grub2/grubenv",
            "/boot/grub2/i386-pc/normal.mod",
        },
        files={
            "/boot/efi/EFI/redhat/grub.cfg": GOOD_BOOTSTRAP,
            "/etc/fstab": "UUID=x /boot/efi vfat umask=0077 0 2\n",
        },
        links={"/etc/grub2.cfg": ETC_SYMLINK_TARGET,
               "/etc/grub2-efi.cfg": ETC_SYMLINK_TARGET},
    )
    result = execute_validation(fe, facts, build_plan(facts),
                                reprobe=lambda: facts)
    assert result.ok
