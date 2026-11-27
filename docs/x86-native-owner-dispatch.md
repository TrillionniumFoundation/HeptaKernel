# Native owner-checked parked-slot dispatch

Extends #200 exact 7c399e17fbbc4ebba3455175f1ec558d38d82525; all parent files and workflows retained. HIA f4 validates the live BSP periodic ISR, distinct aligned low-address owner and slot words, non-exhausted generation and exact owner identity CAS, then returns the opposite task slot. The actual destination-frame load uses this returned slot; independent observer still checks parity, progress and slot identity. Future-generation and aliased-slot calls must return zero. Dedicated identity-CAS deletion must be detected by the future-generation probe, in addition to the 32 inherited scenarios (34 planned total).

This is a fixed two-task, nonnested BSP dispatcher, not a general scheduler or slot authority. Caller supplies addresses; no SMP/atomic multiword claim. All production locks, Linux gates and syscall obligations unchanged. Exact independent CI pending.
