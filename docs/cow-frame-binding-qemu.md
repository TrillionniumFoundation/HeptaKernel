# Live native HIA COW frame binding under QEMU

This experiment links unchanged native `cow_frame_binding.hepta` machine code
into the original restricted CPL0 COW fault path. Native `kernel.hepta` PMM
initializes the E820-admitted 0x600000 region and claims the two physical
pages at 0x601000 and 0x602000. Native HIA installs the active read-only
source PTE, and the CPU warms the actual mapping before the binding call.

The HIA binding entry reads the **actual active PTE** and the
**HIA-initialized live PMM bitmap**, not synthetic bitmaps or PTE copies.
The non-HIA observer independently checks the return code and complete
8,192-byte PMM state, including reserved bytes, and that HIA did not
modify the PTE. Only an admitted call proceeds to the physical write
protection #PF, HIA page copy/counter change, HIA PTE remap,
non-HIA INVLPG/IRETQ and exact original store retry.

Four images execute on both PC 32MiB and Q35 64MiB: legitimate binding
and COW fault recovery, stale expected PTE status 5, missing target
allocation bit status 6, and dishonest always-success HIA replacement.
The hostile replacement is considered *detected* only when the observer
sees the invalid state and refuses to proceed. Return codes and unique
serial markers are checked in the independent QEMU Python observer.
Native source/boot/negative `.text` byte identity is checked before QEMU.

Scope remains **one owner, one CPU, quiescent state**. The physical
addresses, source of the PMM pointer, and source of the PTE pointer are
provided by the non-HIA bridge. This does not authenticate the pointer
against CR3, make COW updates atomic, prevent concurrent PTE publication,
perform shootdowns, establish Linux VM or implement privilege operations
in HIA. The bridge still contains E820 conversion, fault entry, IRETQ,
INVLPG, CR3 and device I/O. No Linux syscall or all-Linux gate is closed.
The full 17-gate and 422-row obligations remain unchanged.
