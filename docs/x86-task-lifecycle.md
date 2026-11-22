# HIA-native bounded two-slot task lifecycle transition

The pinned upstream HIA Core v8 `selfhost_elf` compiler compiles
`src/x86_task_lifecycle.hepta` directly into x86-64 freestanding native
machine code. No C/Rust/assembly translation, inline machine bytes or
host syscall implementation is involved.

Its three-buffer ABI is `(request: readbuf, reply: mutbuf, tasks: mutbuf)`.
The request is exactly four little-endian u64 words
`(operation, expected_leader_tid, expected_worker_tid, new_worker_tid)`.
Operation 0 activates a worker; operation 1 retires it. The reply is exactly
8 bytes and receives the resulting worker TID (or zero). The task memory
is exactly 64 bytes, compatible with the existing
`x86_syscall_task_view.hepta`: two 32-byte tuples
`(TID, TGID, PPID, active)`.

The leader must be live, satisfy `TID == TGID == expected_leader_tid`,
have a positive signed 31-bit TID and a PPID in `[0,2^31-1]`.
Activating a worker requires all four worker words and the expected worker
TID to be zero. The new worker TID must be positive, distinct from the
leader and at most `2^31-1`. On success, the HIA native function writes
`(new_worker_tid, leader_tid, leader_ppid, 1)` into the second record.
Retiring requires the second record to equal
`(expected_worker_tid, leader_tid, leader_ppid, 1)`, with a positive
bounded expected worker TID and requested new worker TID zero. It then
clears all four worker words. All checks precede all stores.

Status returns are 0 success, 1 malformed request, 2 malformed reply,
3 malformed state, 4 unknown operation, 5 invalid/stale leader,
6 stale/inconsistent worker, and 7 invalid new identity. Refused
transitions must preserve the entire task buffer and the entire reply
buffer. In the two-operation single-owner profile, native reads of
getpid/gettid/getppid from the existing independent HIA component
observe the activated state; following retirement the second slot
returns the fixture's -ESRCH sentinel.

The independent Python oracle tests the complete 64-byte post-state
rather than just a status, guard sentinels, invalid lengths, stale IDs,
leader/worker corruption and random activate/retire sequences. The
original independent HIA task-view binary is used for cross-component
interoperability after transitions. A separately compiled dishonest
HIA no-op control must be detected. Two empty-PATH native recompilations
must match the original object byte-for-byte, and the object/shared
library .text must match.

**Limits:** the source of task identities and exclusive ownership is an
untrusted test fixture. Four separate 64-bit writes are *not* an atomic
multiword transaction, even though validation precedes every write.
There is no concurrency synchronization, scheduler, real Linux
`clone`/`fork`/`exit`/`wait`, PID namespace, authenticated task
management, syscall number implementation, hardware context switch,
verified privileged entry or fully HIA-native boot. The existing
non-HIA `boot.S` bridge is retained. All 17 Linux acceptance gates
remain HOLD, including all 422 pinned x86-64 syscall source rows.

Hardware integration and SMP/interrupt safety require independent
qualification before this bounded lifecycle state can be promoted to
real Linux process semantics.
