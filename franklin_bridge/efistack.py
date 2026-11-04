"""Phase 5 - EFI stack population.

Installs the packages that put the EFI bootloader on the (now-mounted) ESP and
ensures the UEFI fallback path is in place:

  * Install shim-x64 + grub2-efi-x64 if missing; ensure grub2-pc is present for
    the later BIOS GRUB reinstall.
  * REINSTALL any EFI-on-ESP package that was already installed, so its files are
    (re)written onto the ESP we just mounted. (A package installed while
    /boot/efi was still a plain directory would otherwise have its files hidden
    under the mount.)
  * Ensure \\EFI\\BOOT\\BOOTX64.EFI exists. On RHEL the shim-x64 package may
    already provide it; if so we leave it alone. If not, we create it from shim
    (plus the fallback binary) so a later firmware switch to UEFI boots with no
    NVRAM entry present.

No efibootmgr / EFI grub2-install here: we are booted in BIOS mode, so NVRAM is
not writable. The fallback path is what makes the eventual UEFI switch work.
"""

# EFI packages whose files live on the ESP.
ESP_PACKAGES = ("shim-x64", "grub2-efi-x64")
# Needed for the Phase 6 BIOS GRUB reinstall (not an ESP package).
BIOS_PACKAGES = ("grub2-pc",)


def plan_efi_packages(facts):
    """Return (to_install, to_reinstall) package lists (pure)."""
    installed = facts.packages
    to_install = []
    to_reinstall = []
    for pkg in ESP_PACKAGES:
        if installed.get(pkg, False):
            to_reinstall.append(pkg)   # already installed -> rewrite onto ESP
        else:
            to_install.append(pkg)
    for pkg in BIOS_PACKAGES:
        if not installed.get(pkg, False):
            to_install.append(pkg)
    return to_install, to_reinstall


def execute_efistack(executor, facts, plan):
    """Perform Phase 5. Returns a summary dict."""
    to_install, to_reinstall = plan_efi_packages(facts)

    if to_install:
        executor.log("-> Install packages: %s" % ", ".join(to_install))
        executor.run(["dnf", "-y", "install"] + to_install, mutates=True)
    if to_reinstall:
        executor.log("-> Reinstall EFI packages onto the ESP: %s"
                     % ", ".join(to_reinstall))
        executor.run(["dnf", "-y", "reinstall"] + to_reinstall, mutates=True)

    esp = plan.esp_mountpoint
    redhat = esp + "/EFI/redhat"
    bootdir = esp + "/EFI/BOOT"

    _verify_populated(executor, redhat)
    fallback_created = _ensure_fallback(executor, redhat, bootdir)

    return {
        "installed": to_install,
        "reinstalled": to_reinstall,
        "fallback_created": fallback_created,
    }


def _verify_populated(executor, redhat):
    """Confirm the EFI bootloader landed on the ESP (skipped in dry-run)."""
    if getattr(executor, "dry_run", False):
        return
    missing = [name for name in ("grubx64.efi", "shimx64.efi")
               if not executor.exists(redhat + "/" + name)]
    if missing:
        raise RuntimeError(
            "EFI stack not populated on the ESP; missing %s in %s "
            "(is the ESP mounted and were the packages installed?)"
            % (", ".join(missing), redhat))


def _ensure_fallback(executor, redhat, bootdir):
    """Ensure \\EFI\\BOOT\\BOOTX64.EFI exists. Returns True if we created it."""
    target = bootdir + "/BOOTX64.EFI"
    if executor.exists(target):
        executor.log("   UEFI fallback already present (%s); leaving it" % target)
        return False

    executor.log("-> Set up UEFI fallback at %s" % target)
    executor.makedirs(bootdir)
    executor.copy(redhat + "/shimx64.efi", target)

    # The fallback binary creates the NVRAM entry on first UEFI boot, reading
    # BOOTX64.CSV (shipped by shim-x64 in the redhat dir).
    fb_src = redhat + "/fbx64.efi"
    if executor.exists(fb_src):
        executor.copy(fb_src, bootdir + "/fbx64.efi")
    else:
        executor.log("   note: %s not found; NVRAM self-heal may be unavailable"
                     % fb_src)
    return True
