"""Phase 3 - Partition surgery (DESTRUCTIVE).

Converts the disk's DOS label to GPT and creates the two partitions the hybrid
boot setup needs: a BIOS Boot partition (type ef02) and an EFI System Partition
(type ef00). Existing partitions keep their offsets and sizes.

As with the other phases: a pure planner builds the exact commands, and an
executor-driven runner performs them (honoring dry-run). Each step is skippable
so a partially-completed run can be resumed.

Live-disk note: because existing partitions are mounted, the kernel will not
re-read the whole table. We register only the NEW partitions with `partx -a`;
the full re-read happens at the required reboot. Existing partitions keep their
sectors, so the kernel's view stays consistent in the meantime.
"""
from .executor import Executor
from .inventory import _part_device


class PartitionStep(object):
    """A single planned command, with a human description and the role it fills."""

    def __init__(self, desc, argv):
        self.desc = desc
        self.argv = argv

    def __repr__(self):
        return "PartitionStep(%r, %r)" % (self.desc, self.argv)

    def __eq__(self, other):
        return (isinstance(other, PartitionStep)
                and self.desc == other.desc and self.argv == other.argv)


def plan_partition_commands(facts, plan):
    """Return (steps, new_parts) where new_parts is a list of (number, role).

    Pure: computes partition numbers and sector counts from facts + plan.
    """
    disk = facts.disk.path
    sector = facts.disk.sector_size or 512
    steps = []
    new_parts = []

    if plan.convert_to_gpt:
        steps.append(PartitionStep(
            "Convert MBR/DOS label to GPT",
            ["sgdisk", "-g", disk],
        ))

    existing_numbers = [p.number for p in facts.partitions]
    next_num = (max(existing_numbers) if existing_numbers else 0) + 1

    if plan.create_biosboot is not None:
        n = next_num
        next_num += 1
        sectors = plan.create_biosboot.size_bytes // sector
        steps.append(PartitionStep(
            "Create BIOS Boot partition #%d (%d sectors, %s)"
            % (n, sectors, plan.create_biosboot.parttype_code),
            ["sgdisk",
             "-n", "%d:0:+%d" % (n, sectors),
             "-t", "%d:%s" % (n, plan.create_biosboot.parttype_code),
             "-c", "%d:%s" % (n, plan.create_biosboot.name),
             disk],
        ))
        new_parts.append((n, "biosboot"))

    if plan.create_esp is not None:
        n = next_num
        next_num += 1
        sectors = plan.create_esp.size_bytes // sector
        steps.append(PartitionStep(
            "Create EFI System Partition #%d (%d sectors, %s)"
            % (n, sectors, plan.create_esp.parttype_code),
            ["sgdisk",
             "-n", "%d:0:+%d" % (n, sectors),
             "-t", "%d:%s" % (n, plan.create_esp.parttype_code),
             "-c", "%d:%s" % (n, plan.create_esp.name),
             disk],
        ))
        new_parts.append((n, "esp"))

    return steps, new_parts


def execute_partitioning(executor, facts, plan):
    """Perform Phase 3. Returns a summary dict. Raises on verification failure."""
    disk = facts.disk.path
    steps, new_parts = plan_partition_commands(facts, plan)

    if not steps:
        executor.log("Partitioning: nothing to do (already converted).")
        return {"steps": [], "new_parts": [], "verified": []}

    for step in steps:
        executor.log("-> %s" % step.desc)
        executor.run(step.argv, mutates=True)

    # Register only the new partitions with the kernel (existing ones are busy).
    new_devices = []
    for number, role in new_parts:
        executor.run(["partx", "-a", "--nr", str(number), disk], mutates=True)
        new_devices.append((number, role, _part_device(disk, number)))

    verified = _verify_new_partitions(executor, new_devices)

    return {
        "steps": [s.desc for s in steps],
        "new_parts": new_parts,
        "verified": verified,
    }


def _verify_new_partitions(executor, new_devices):
    """Confirm the new partition device nodes exist (skipped in dry-run)."""
    if getattr(executor, "dry_run", False):
        return []
    verified = []
    missing = []
    for number, role, dev in new_devices:
        if executor.exists(dev):
            executor.log("   verified %s (%s)" % (dev, role))
            verified.append(dev)
        else:
            missing.append(dev)
    if missing:
        raise RuntimeError(
            "partition surgery did not produce expected device(s): %s"
            % ", ".join(missing)
        )
    return verified
