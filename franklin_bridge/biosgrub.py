"""Phase 6 - BIOS GRUB reinstall.

Reinstalls the legacy (i386-pc) GRUB onto the disk:

    grub2-install --target i386-pc <disk>

This writes GRUB's boot.img to the protective MBR's boot-code area and embeds
core.img into the BIOS Boot partition (ef02) created in Phase 3. It is the step
that restores reboot-safety after the Phase 3 GPT conversion clobbered the old
core image that lived in the post-MBR gap.

grub2-install is idempotent, so this phase can be re-run safely.
"""


def grub2_install_command(facts):
    """The BIOS GRUB install command for this disk (pure)."""
    return ["grub2-install", "--target", "i386-pc", facts.disk.path]


def execute_bios_grub(executor, facts, plan):
    """Perform Phase 6. Returns a summary dict."""
    if not plan.needs_bios_grub_reinstall:
        executor.log("BIOS GRUB reinstall not needed; skipping.")
        return {"skipped": True, "disk": facts.disk.path}

    executor.log("-> Reinstall BIOS GRUB to %s "
                 "(embeds core image into the BIOS Boot partition)"
                 % facts.disk.path)
    executor.run(grub2_install_command(facts), mutates=True)

    _verify_modules(executor)
    return {"skipped": False, "disk": facts.disk.path}


def _verify_modules(executor):
    """Confirm grub2-install populated the i386-pc modules (skipped in dry-run)."""
    if getattr(executor, "dry_run", False):
        return
    marker = "/boot/grub2/i386-pc/normal.mod"
    if not executor.exists(marker):
        raise RuntimeError(
            "BIOS GRUB modules not found at %s after grub2-install" % marker)
