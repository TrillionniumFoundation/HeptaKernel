# Experimental versioned ready-state word

This additive experiment uses HIA-native locked compare/exchange and MFENCE
to update a single caller-owned aligned x86-64 word. The low 32 bits are a
ready bitmap and the high 32 bits are a nonwrapping generation. It accepts
a fixed count of 1..32 slots, a task index, an expected complete word and a
desired ready bit. A changed bit and the incremented generation are
published together by one CAS. Return 0 means the change was published;
6 means invalid shape or exhausted generation; 7 means the requested bit
already has its desired value in the supplied expected state (no access
to the live word is required); 9 means a valid changing request lost the
CAS. The count must remain fixed by the caller and the slot must designate
accessible normal RAM; address admission is not resource authority.
The generation must not be reset or reused during a word's lifetime.
A duplicate request does not prove that the live word has that bit value.

The 64-slot pure selector remains unchanged; this separate 32-slot packed
state representation is not a reduction of that contract or a general
64-task queue. The independent host oracle exercises invalid parameters,
stale generations with the same bitmap, generation exhaustion, canaries,
32 rounds of eight contenders, and 4,000 accepted concurrent toggles.
Three separately compiled wrong implementations must fail the oracle.
The native compiler is rebuilt from the pinned experimental Hepta commit,
with two empty-PATH subject compilations and exact compiler/source hashes.

Local qualification: 23,698 sequential calls, 256 single-winner race calls,
4,035 toggle calls including 4,000 accepted updates, all three controls
detected. This is host native execution, not live IRQ dispatch, task
resource authority, general SMP, Linux acceptance, or a production lock
change. Original 17 gates and 422 syscall obligations remain unchanged.

Inherited qualification note: #202 PR run 45586184248 job 139108259993
failed the existing irq-r15-save-wrong PC control with serial A, exit 37,
rather than the required S/35; its original failure remains open. Exact
guest32 image 30a5b9608c7fb083db2e6580d024fdf6796680d28332c45af9d059b1e44dcabf
replayed on desktop 12 times each PC/Q35 with S/35. This does not resolve
the independent failure or identify its cause; the inherited oracle,
timeouts, and all acceptance criteria are unmodified.
