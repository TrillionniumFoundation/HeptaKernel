# Native E820 discovery to physical PMM in the Multiboot fixture

Two opt-in positive images use the existing real Multiboot map. The explicit
non-HIA transport copies every normalized firmware row, adds the live kernel
image/BSS/stack, loader info and original map reservations, and supplies the
result to the unchanged HIA candidate search. It refuses if all records do
not fit. Search is confined to the original mapped 4–8 MiB fixture window.

The returned base drives both existing native exact admission gates before any
of these frames is touched. The original E820 gate receives the original
firmware rows and returned range; the separate native reservation gate checks
the exact range against the known reservations. Only then does the original
native PMM initialize at that base and allocate two pages after the one-page
reserved prefix. The observer writes and reads distinct values at the same
offset in each returned physical page, then restores the original two words.

The two variants ask for three pages aligned to 1 MiB. Only the second supplies
a caller-declared one-byte test reservation at 0x400001 to both discovery and
the exact reservation gate. This changes the actual selected base from
0x400000 to 0x500000 and the allocated base from 0x401000 to 0x501000.
The caller consumes the returned address; it does not substitute an expected
fixture address. The independent host observer checks the expected addresses.

```sh
make HEPTA_COMPILER=/path/to/pinned-compiler test-e820-discovery-boot
```

The test starts both variants on PC/32 MiB and Q35/64 MiB, expects exact serial
order and exit 33, and also runs the untouched fixed default guest on both.
For each path it verifies the actual guest text at the relevant native ABI
symbols against the freshly compiled objects. The report retains commands,
guest hashes, original outputs, and source/object/text hashes.
See [the local report](../validation/e820-discovery-qemu.json).

This is an opt-in, single-owner QEMU guest fixture. It does not replace the
default path, authenticate firmware, discover arbitrary hardware/UEFI RAM,
provide concurrent physical ownership, or close any full Linux acceptance
gate. Startup, handoff transport, and physical observation remain explicitly
non-HIA. The fixture adds no fault-injection or bypass test.
