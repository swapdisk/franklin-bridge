"""Phase 3 - Partition surgery (DESTRUCTIVE), using sfdisk.

Converts the disk's DOS label to GPT and creates the two partitions the hybrid
boot setup needs: a BIOS Boot partition and an EFI System Partition. Existing
partitions keep their exact offsets and sizes.

We deliberately do NOT depend on gdisk/sgdisk (not shipped on RHEL 10). Instead:

  * Conversion (DOS -> GPT) is done by reading the current layout with
    `sfdisk -d`, rewriting it as a GPT script (existing partitions preserved at
    identical start/size, MBR type bytes translated to GPT type GUIDs) plus the
    new partitions, and applying it in one `sfdisk` call.
  * On an already-GPT disk (resume), missing partitions are added with
    `sfdisk --append`, touching nothing else.

Safety: preflight refuses extended/logical partitions and any MBR type we can't
translate, so this only ever runs on a small set of known primary partitions.
After writing, we verify the new device nodes appeared and that every preserved
partition kept its exact start/size (else we raise, and the Phase 2 backup can
restore the original table).

Live-disk note: existing partitions are mounted, so the kernel won't re-read the
whole table; we register only the NEW partitions with `partx -a`. Existing
partitions keep their sectors, so the kernel's view stays consistent until the
reboot.
"""
from .inventory import _part_device, _sfdisk_dump_partitions
from .model import MBR_TO_GPT_GUID


def planned_new_partitions(facts, plan):
    """Return [(number, role)] for the partitions to be created (pure)."""
    existing = [p.number for p in facts.partitions]
    next_num = (max(existing) if existing else 0) + 1
    out = []
    if plan.create_biosboot is not None:
        out.append((next_num, "biosboot"))
        next_num += 1
    if plan.create_esp is not None:
        out.append((next_num, "esp"))
        next_num += 1
    return out


def _mbr_type_to_guid(type_str):
    try:
        value = int(type_str, 16)
    except (TypeError, ValueError):
        raise ValueError("unrecognized MBR partition type %r" % (type_str,))
    if value not in MBR_TO_GPT_GUID:
        raise ValueError("unsupported MBR partition type %r" % (type_str,))
    return MBR_TO_GPT_GUID[value]


def _spec_line(spec, sector_size):
    sectors = spec.size_bytes // sector_size
    return 'size=%d, type=%s, name="%s"' % (sectors, spec.parttype_guid, spec.name)


def build_gpt_script(dump_text, new_specs, sector_size):
    """Build an sfdisk GPT script: preserved partitions + new ones (pure).

    Raises ValueError if a preserved partition has an MBR type we don't know how
    to translate (preflight should have refused this already).
    """
    body = []
    for part in _sfdisk_dump_partitions(dump_text):
        guid = _mbr_type_to_guid(part["type"])
        body.append("start=%d, size=%d, type=%s"
                    % (part["start"], part["size"], guid))
    for spec in new_specs:
        body.append(_spec_line(spec, sector_size))
    return "label: gpt\nunit: sectors\n\n" + "\n".join(body) + "\n"


def append_line(spec, sector_size):
    """One sfdisk script line to append a partition to an existing GPT (pure)."""
    return _spec_line(spec, sector_size) + "\n"


def execute_partitioning(executor, facts, plan):
    """Perform Phase 3. Returns a summary dict. Raises on verification failure."""
    disk = facts.disk.path
    sector_size = facts.disk.sector_size or 512
    new_parts = planned_new_partitions(facts, plan)

    specs_by_role = {}
    if plan.create_biosboot is not None:
        specs_by_role["biosboot"] = plan.create_biosboot
    if plan.create_esp is not None:
        specs_by_role["esp"] = plan.create_esp

    if not plan.convert_to_gpt and not new_parts:
        executor.log("Partitioning: nothing to do (already converted).")
        return {"converted": False, "new_parts": [], "verified": []}

    preserved = []  # (start, size) expected to survive a conversion
    if plan.convert_to_gpt:
        specs = [specs_by_role[role] for (_n, role) in new_parts]
        executor.log("-> Convert %s to GPT (preserving existing partitions) "
                     "and add %d new partition(s)" % (disk, len(specs)))
        if executor.dry_run:
            executor.log("[dry-run] would run: sfdisk -d %s  (read layout)" % disk)
            executor.log("[dry-run] would rewrite as GPT via: sfdisk --no-reread %s"
                         % disk)
        else:
            dump = executor.capture(["sfdisk", "-d", disk])
            preserved = [(p["start"], p["size"])
                         for p in _sfdisk_dump_partitions(dump)]
            script = build_gpt_script(dump, specs, sector_size)
            executor.run_input(["sfdisk", "--no-reread", disk], script,
                               mutates=True)
    else:
        for (_n, role) in new_parts:
            spec = specs_by_role[role]
            executor.log("-> Append %s to the GPT" % spec.name)
            executor.run_input(["sfdisk", "--append", disk],
                               append_line(spec, sector_size), mutates=True)

    # Register only the new partitions with the kernel (existing ones are busy).
    new_devices = []
    for (number, role) in new_parts:
        executor.run(["partx", "-a", "--nr", str(number), disk], mutates=True)
        new_devices.append((number, role, _part_device(disk, number)))

    verified = _verify(executor, facts, plan, new_devices, preserved, sector_size)
    return {
        "converted": plan.convert_to_gpt,
        "new_parts": new_parts,
        "verified": verified,
    }


def _verify(executor, facts, plan, new_devices, preserved, sector_size):
    """Confirm new device nodes exist and preserved geometry is intact."""
    if getattr(executor, "dry_run", False):
        return []

    missing = [dev for (_n, _r, dev) in new_devices if not executor.exists(dev)]
    if missing:
        raise RuntimeError(
            "partition surgery did not produce expected device(s): %s"
            % ", ".join(missing))

    if plan.convert_to_gpt and preserved:
        after = {p["start"]: p["size"]
                 for p in _sfdisk_dump_partitions(
                     executor.capture(["sfdisk", "-d", facts.disk.path]))}
        for (start, size) in preserved:
            if after.get(start) != size:
                raise RuntimeError(
                    "post-conversion geometry mismatch at sector %d "
                    "(expected size %d sectors, found %s); the original table is "
                    "in the Phase 2 backup" % (start, size, after.get(start)))

    verified = []
    for (_n, role, dev) in new_devices:
        executor.log("   verified %s (%s)" % (dev, role))
        verified.append(dev)
    return verified
