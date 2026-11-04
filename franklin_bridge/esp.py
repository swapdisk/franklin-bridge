"""Phase 4 - EFI System Partition: filesystem, migration, and mount.

Formats the ESP as FAT32, adds an fstab entry by UUID, and mounts it at
/boot/efi. Crucially, it does NOT simply bury whatever already lives at
/boot/efi (on a BIOS install that is at least the grub2-common-owned
EFI/redhat directory, and on a misconfigured system possibly real
grub2-efi-x64 files). Instead it *migrates* that content onto the new ESP:

    move /boot/efi aside -> mount empty ESP -> copy preserved content onto it
    -> remove the aside copy

so nothing is lost or hidden, and a pre-existing EFI stack ends up on the ESP
where it belongs.
"""
from .inventory import _part_device
from .partition import plan_partition_commands

ESP_FSTAB_OPTIONS = "umask=0077,shortname=winnt"
ORIG_SUFFIX = ".franklin-orig"


def fstab_line(uuid, mountpoint="/boot/efi", options=ESP_FSTAB_OPTIONS):
    """Build the /etc/fstab line for the ESP (pure)."""
    return "UUID=%s  %s  vfat  %s  0 2\n" % (uuid, mountpoint, options)


def fstab_has_mount(fstab_text, mountpoint):
    """True if fstab already has a (non-comment) entry for this mount point."""
    for line in fstab_text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        fields = s.split()
        if len(fields) >= 2 and fields[1] == mountpoint:
            return True
    return False


def target_esp_device(facts, plan):
    """The ESP device path: the existing one, or the one Phase 3 will create."""
    if facts.existing_esp is not None:
        return facts.existing_esp.device
    _, new_parts = plan_partition_commands(facts, plan)
    for number, role in new_parts:
        if role == "esp":
            return _part_device(facts.disk.path, number)
    return None


def execute_esp(executor, facts, plan):
    """Perform Phase 4. Returns a summary dict."""
    dev = target_esp_device(facts, plan)
    if dev is None:
        raise RuntimeError("no EFI System Partition to format (none planned or found)")
    mountpoint = plan.esp_mountpoint
    orig = mountpoint.rstrip("/") + ORIG_SUFFIX

    if executor.ismount(mountpoint):
        executor.log("ESP already mounted at %s; skipping Phase 4." % mountpoint)
        return {"device": dev, "mountpoint": mountpoint,
                "skipped": True, "migrated": False}

    if _device_fstype(executor, dev) == "vfat":
        executor.log("-> %s already has a FAT filesystem; not reformatting" % dev)
    else:
        executor.log("-> Format %s as FAT32" % dev)
        executor.run(["mkfs.vfat", "-F", "32", dev], mutates=True)

    if executor.dry_run:
        uuid = "<esp-uuid>"
    else:
        uuid = executor.capture(
            ["blkid", "-s", "UUID", "-o", "value", dev]).strip()
        if not uuid:
            raise RuntimeError("could not read UUID of new ESP %s" % dev)

    # Preserve whatever currently lives at the mount point.
    entries = executor.listdir(mountpoint) if executor.exists(mountpoint) else []
    migrated = bool(entries)
    if migrated:
        executor.log("-> Preserve existing %s contents (%s) for migration"
                     % (mountpoint, ", ".join(sorted(entries))))
        executor.run(["mv", mountpoint, orig], mutates=True)
    executor.makedirs(mountpoint)

    fstab_changed = _ensure_fstab(executor, uuid, mountpoint)
    if fstab_changed:
        _daemon_reload(executor)

    executor.log("-> Mount ESP at %s" % mountpoint)
    executor.run(["mount", mountpoint], mutates=True)

    if migrated:
        executor.log("-> Migrate preserved contents onto the ESP")
        executor.run(["cp", "-r", orig + "/.", mountpoint + "/"], mutates=True)
        executor.run(["rm", "-rf", orig], mutates=True)

    return {"device": dev, "uuid": uuid, "mountpoint": mountpoint,
            "skipped": False, "migrated": migrated}


def _ensure_fstab(executor, uuid, mountpoint, path="/etc/fstab"):
    """Append the ESP fstab entry if missing. Returns True if it was added."""
    text = executor.read_text(path)
    if fstab_has_mount(text, mountpoint):
        executor.log("   %s already has an entry for %s; leaving it"
                     % (path, mountpoint))
        return False
    prefix = "" if (text == "" or text.endswith("\n")) else "\n"
    executor.log("-> Add %s entry to %s" % (mountpoint, path))
    executor.append_text(path, prefix + fstab_line(uuid, mountpoint))
    return True


def _device_fstype(executor, dev):
    """Return the filesystem type on a device, or '' if none (dry-run -> None)."""
    if executor.dry_run:
        return None
    return executor.capture(
        ["blkid", "-s", "TYPE", "-o", "value", dev], check=False, default=""
    ).strip()


def _daemon_reload(executor):
    """Tell systemd to re-read fstab after we changed it (tolerant of failure)."""
    executor.log("-> Reload systemd units (fstab changed)")
    try:
        rc = executor.run(["systemctl", "daemon-reload"], mutates=True, check=False)
    except OSError:
        executor.log("   systemctl not available; skipping daemon-reload")
        return
    if rc:
        executor.log("   systemctl daemon-reload returned %s; continuing" % rc)
