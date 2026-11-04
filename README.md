# Franklin Bridge

Franklin Bridge converts a running Red Hat Enterprise Linux system that boots in
**Legacy BIOS** mode into a **hybrid-boot** configuration — one that boots
correctly whether the firmware is later set to Legacy BIOS *or* UEFI. This lets
you prepare a system for UEFI ahead of time and flip the firmware mode whenever
it's convenient, with no further changes to the OS.

It automates the partition prerequisites (DOS→GPT conversion, a BIOS Boot
partition, and an EFI System Partition) and the unified GRUB2 setup described in
Red Hat's knowledge base.

> **Status: early development.** Targets RHEL 8, 9, and 10 on x86_64. More
> documentation, usage instructions, and the conversion workflow are on the way.

## Learn more

See the [design document](docs/design.md) for goals, scope, the target layout,
and the phased implementation plan.

## License

[MIT](LICENSE)
