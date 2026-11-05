"""Phase 7 - Unified GRUB2 configuration (KB 6718341 section 3).

Produces the layout that boots identically under BIOS and UEFI:

  * /boot/grub2/grub.cfg          - the REAL config (grub2-mkconfig)
  * /boot/grub2/grubenv           - a real file (not a symlink)
  * /boot/efi/EFI/redhat/grub.cfg - a BOOTSTRAP config that finds /boot by UUID
                                    and chains to the real config
  * /etc/grub2.cfg, /etc/grub2-efi.cfg -> ../boot/grub2/grub.cfg

Under UEFI, shim -> grubx64.efi reads the bootstrap config, which does a
`search --fs-uuid` for the /boot filesystem and then `configfile`s the real
config. Under BIOS, core.img reads the real config directly. Both modes end up
executing the same /boot/grub2/grub.cfg.
"""

GRUB_HOME = "/boot/grub2"
REAL_CFG = GRUB_HOME + "/grub.cfg"
GRUBENV = GRUB_HOME + "/grubenv"
ETC_SYMLINKS = ("/etc/grub2.cfg", "/etc/grub2-efi.cfg")
ETC_SYMLINK_TARGET = "../boot/grub2/grub.cfg"

BOOTSTRAP_TEMPLATE = (
    "connectefi scsi\n"
    "search --no-floppy --fs-uuid --set=dev {uuid}\n"
    "set prefix=($dev){grub_dir}\n"
    "export $prefix\n"
    "configfile $prefix/grub.cfg\n"
)


def render_bootstrap_grubcfg(boot_uuid, grub_dir):
    """Render the EFI bootstrap grub.cfg (pure). See KB section 3.1 item 4."""
    return BOOTSTRAP_TEMPLATE.format(uuid=boot_uuid, grub_dir=grub_dir)


def execute_unified_config(executor, facts, plan):
    """Perform Phase 7. Returns a summary dict."""
    efi_home = plan.esp_mountpoint + "/EFI/redhat"
    bootstrap_cfg = efi_home + "/grub.cfg"

    # 1. Ensure grubenv is a real file in /boot/grub2 (not a symlink to the ESP).
    _ensure_real_grubenv(executor, GRUBENV)

    # 2. (Re)generate the real config.
    executor.log("-> Generate real GRUB config: %s" % REAL_CFG)
    executor.run(["grub2-mkconfig", "-o", REAL_CFG], mutates=True)

    # 3. Write the EFI bootstrap config that chains to the real config.
    if executor.dry_run:
        boot_uuid, grub_dir = "<boot-fs-uuid>", "/grub2"
    else:
        boot_uuid = executor.capture(
            ["grub2-probe", "--target=fs_uuid", GRUB_HOME]).strip()
        grub_dir = executor.capture(
            ["grub2-mkrelpath", GRUB_HOME]).strip()
    executor.log("-> Write EFI bootstrap config: %s" % bootstrap_cfg)
    executor.write_text(bootstrap_cfg,
                        render_bootstrap_grubcfg(boot_uuid, grub_dir))

    # 4. Point both /etc symlinks at the real config.
    for link in ETC_SYMLINKS:
        _ensure_symlink(executor, link, ETC_SYMLINK_TARGET)

    # 5. Tidy up a possible packaging leftover.
    rpmnew = GRUBENV + ".rpmnew"
    if executor.exists(rpmnew):
        executor.log("-> Remove packaging leftover: %s" % rpmnew)
        executor.run(["rm", "-f", rpmnew], mutates=True)

    return {"bootstrap": bootstrap_cfg, "real": REAL_CFG,
            "boot_uuid": boot_uuid, "grub_dir": grub_dir}


def _ensure_real_grubenv(executor, path):
    if executor.islink(path):
        executor.log("-> Replace grubenv symlink with a real file: %s" % path)
        executor.run(["rm", "-f", path], mutates=True)
        executor.run(["grub2-editenv", path, "create"], mutates=True)
    elif not executor.exists(path):
        executor.log("-> Create grubenv: %s" % path)
        executor.run(["grub2-editenv", path, "create"], mutates=True)
    else:
        executor.log("   grubenv is already a real file: %s" % path)


def _ensure_symlink(executor, link_path, target):
    if executor.islink(link_path) and executor.readlink(link_path) == target:
        executor.log("   %s already -> %s" % (link_path, target))
        return
    if executor.islink(link_path) or executor.exists(link_path):
        executor.run(["rm", "-f", link_path], mutates=True)
    executor.log("-> Symlink %s -> %s" % (link_path, target))
    executor.run(["ln", "-s", target, link_path], mutates=True)
