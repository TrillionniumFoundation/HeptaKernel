# HIA-native one-task x86-64 getpid hardware fixture

Scope: the pinned Linux 7.3.4 `__x64_sys_getpid` interface at syscall number 39.
`src/x86_syscall_one_task.hepta` is compiled by the exact locked HIA Core v8
`selfhost_elf` compiler. Its two-register ABI is `(nr, caller_supplied_tgid)`
and its sole implemented success result is the positive thread-group ID for
`nr == 39`. The caller must provide a plausible positive ID not exceeding
2^31 - 1. Invalid task snapshots fail closed with an internal `-ESRCH`
marker; real Linux getpid has no such failure path under a valid task.

Every other syscall number returns the Linux x86-64 negative `-ENOSYS`
value (u64 0xffffffffffffffda), **which confers no implementation credit**.
The original 422 syscall source rows, x32/IA32 obligations and all 17
full-acceptance gates remain unchanged.

The fixed-task QEMU observer enters CPL3 using the existing, explicitly
non-HIA `SYSRETQ` bridge, issues the actual hardware `SYSCALL` instruction,
passes the live RAX syscall number and fixed fixture TGID 4242 to original HIA
machine code on a separate supervisor stack, returns that native HIA result
in RAX through a real `SYSRETQ`, and checks RAX in the actual CPL3 `#UD`
trap before touching AX. Separate PC/Q35 images test real getpid=4242 and
unknown number=1024 -> -ENOSYS. Wrong status or short-circuit fail the
hardware observer. Native test independently covers valid, invalid, unknown
and dishonest always-4242 HIA components; object/shared .text and two
empty-PATH deterministic rebuilds are checked.

This fixture **does not** implement task/thread-group creation, scheduler,
credential storage, TID/TGID synchronization, fork, namespace PID translation,
signals, or general Linux dispatch. `caller_supplied_tgid` is neither
authenticated nor derived from a running task. All privileged instructions,
RIP/RSP capture, context handling and exception entry still live in
`arch/x86_64/boot.S`, the non-HIA test bridge. No Linux ABI row is marked
complete by this milestone. The full target remains HOLD.
