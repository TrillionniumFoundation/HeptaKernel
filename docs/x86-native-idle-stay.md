# Actual native idle stay without a wakeup (experimental)

The original #213 source and 46-case suite are preserved. This change adds
an independent hardware scenario, not a new HIA instruction or dispatcher.
Two ordinary tasks block; the last transitions to idle. At the third
timer IRQ, both remain blocked. The actual native idle selector first
rejects a stale expected ready word (66), then returns no peer (64).
The observer checks unchanged ready generation/bitmap, owner generation,
parked task frames and empty idle slot, acknowledges the timer and returns
the same live idle frame through the original native IRETQ path. The next
interrupt sees a second completed HLT and wakes task 0; task 1 remains
blocked. Five interrupts, three actual task switches, one idle stay.
Owner generation counts switches, not IRQs.

Independent source mutants remove the idle identity CAS or return a wrong
no-peer result. Both must be detected as I on PC and Q35. Existing cases
remain unmodified and are rerun before the new eight cases.

Qualification: desktop r2, 54/54 PC/Q35, 10020 idle, 9512 running-block,
98219 ordinary compensation and 1100 resolver host calls. Original native
compiler and idle object hashes preserved. #212 block compensation is a
separate inherited workflow, not counted as part of these 54 cases.

A prior unmodified inherited case failed in r1: Q35 idle-no-advance
returned A/37 rather than I/35; the same exact image subsequently returned
I/35 on all 16 diagnostic replays. This does not establish the root cause
or erase the failure. The unchanged full suite passed r2. No timeout or
assertion was relaxed. The failed run and replay data are below.

This still uses a fixed nonnested BSP with caller-owned stacks and assembly
observer, HLT and dispatch calls. No general atomic transaction, CPU
authority, SMP, idle rollback, synchronous syscall sleep or full Linux
acceptance claim is made. All original gates remain HOLD.

Failed r1 row:

```json
{
  "case": "idle-no-advance",
  "machine": "q35",
  "image_sha256": "bc5bc65292f92c5bc6b69cab5232de433b450f14d6d8a4fba3759d28e3a6b47a",
  "expected_rc": 35,
  "expected_serial": "I",
  "status": "FAIL",
  "returncode": 37,
  "serial": "A",
  "stderr": ""
}
```

Exact image diagnostic replays:

```json
[
  {
    "i": 0,
    "rc": 35,
    "serial": "I"
  },
  {
    "i": 1,
    "rc": 35,
    "serial": "I"
  },
  {
    "i": 2,
    "rc": 35,
    "serial": "I"
  },
  {
    "i": 3,
    "rc": 35,
    "serial": "I"
  },
  {
    "i": 4,
    "rc": 35,
    "serial": "I"
  },
  {
    "i": 5,
    "rc": 35,
    "serial": "I"
  },
  {
    "i": 6,
    "rc": 35,
    "serial": "I"
  },
  {
    "i": 7,
    "rc": 35,
    "serial": "I"
  },
  {
    "i": 8,
    "rc": 35,
    "serial": "I"
  },
  {
    "i": 9,
    "rc": 35,
    "serial": "I"
  },
  {
    "i": 10,
    "rc": 35,
    "serial": "I"
  },
  {
    "i": 11,
    "rc": 35,
    "serial": "I"
  },
  {
    "i": 12,
    "rc": 35,
    "serial": "I"
  },
  {
    "i": 13,
    "rc": 35,
    "serial": "I"
  },
  {
    "i": 14,
    "rc": 35,
    "serial": "I"
  },
  {
    "i": 15,
    "rc": 35,
    "serial": "I"
  }
]
```
