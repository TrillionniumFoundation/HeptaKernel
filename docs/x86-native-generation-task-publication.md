# Generation-bound active-task publication

Parent #199 exact ce65ddb4a6539c0f2781f0435c37de1ffe6a4185. Parent source and tests unchanged. New HIA f3 uses a monotone 64-bit owner word: low bit is task identity, upper bits distinguish repeated cycles. Single CAS increments the entire word, with maximum-value refusal before slot access. All APIC, frame, slot and identity-CAS guards retained. Observer checks full new word and parity, and original GPR/RIP/RSP evidence remains.

Each successful switch tests future same-parity and maximum expected generation refusal. After two real switches replay an old same-parity generation with current parked and consumed slots; require no owner change. Dedicated replay exits at third switch; normal positives check two replay refusals and four publications. Previous CAS deletion and all controls retained. Planned 32 PC/Q35 cases; no PASS before exact CI.

Restricted fixed BSP, not arbitrary stale frame provenance, authority, concurrent multiword transaction or general scheduler. Production lock and Linux obligations unchanged.
