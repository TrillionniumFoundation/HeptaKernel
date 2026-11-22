# Native HIA two-record task-snapshot syscall view

The fixed HIA Core v8 selfhost_elf compiler produces x86-64 native machine
code for `src/x86_syscall_task_view.hepta`. It accepts the **caller-supplied**
`(request: readbuf, reply: mutbuf, snapshot: readbuf)` native buffer ABI. The request has 16 little-endian bytes `(syscall_nr, active_slot)`, and the reply receives eight result bytes on success. Wrong request/reply length is refused before accessing task bytes. The snapshot is
exactly 64 bytes: two 32-byte little-endian records of TID, TGID, PPID,
active flag. Slots are 0 or 1, active flag exactly 1, identities are bounded
to positive signed 31-bit values (PPID may be zero). For non-leader threads,
the other slot must contain a live leader with TID==TGID==the current TGID;
live slots may not duplicate TID.

The HIA native routine reads the selected record and peer, does not modify
the input buffer, and returns the selected value for x86-64 syscall numbers
39 (getpid/TGID), 186 (gettid/TID) and 110 (getppid/PPID).
Unsupported syscall numbers return -ENOSYS, invalid slots/inconsistent
records -ESRCH, and wrong snapshot sizes -EINVAL. Those last two outcomes
are **fixture-admission failures**, not claims about Linux's live getpid or
gettid error contracts. Exact-length input ensures no out-of-bounds reads.
An independently implemented Python oracle verifies valid leader/worker
cases, duplicate IDs, dead group leaders, malformed buffers, length
boundaries and caller-provided corruptions; a separately compiled dishonest
constant-PID HIA fixture must fail. The native object and shared .text
match, and two empty-PATH rebuilds must be identical.

This is an intermediate step from a scalar test-only TGID to two snapshot
records; it is **not** authenticated task state, scheduling, live thread
creation, namespace translation, shared-memory atomic snapshotting, RCU,
a real Linux process subsystem, or any complete Linux ABI row. There is
no claim of actual HIA privileged SYSCALL or SYSRETQ execution. Linux's
fixed full acceptance remains 17/17 HOLD and all original syscall obligations
remain in place.

An isolated QEMU PC/32MiB and Q35/64MiB fixture executes a real ring-3
SYSCALL(186), passes assembler-constructed two-record snapshots to the
original native HIA three-buffer routine, and returns through a **non-HIA**
SYSRETQ bridge. The CPL3 hardware exception observer verifies RAX=4243.
A separately compiled adversarial image corrupts the leader TGID and must
return -ESRCH in the same CPL3 RAX register. The snapshot is test-only data,
not an authenticated kernel task or full Linux syscall implementation.
