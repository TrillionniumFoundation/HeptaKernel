# Native forward frame and owner composition (experimental HOLD)

Parent: exact 68699c116db45ad0401af986327b805c26be86a7 (#222).
The new HIA export combines the existing bounded forward frame transfer and
owner publication in one native call. Its six scalar arguments match the
guarded reverse ABI. It binds the departing ID to the expected owner,
rejects excess topology bits, owner alignment/range/stack/table alias and
owner generation overflow before transfer; the existing frame composition
validates the bounded table and both frame/stack intervals. Existing owner
publication checks the live BSP timer ISR and exact parked and consumed slots.
A failed forward frame stage returns its original code; owner refusal after
successful transfer returns 68, not a retryable success. Caller must verify
the original live owner and use the separately qualified reverse/ready
compensation, or fail-stop. No owner rollback after commit is implied.

The independent observer forces stale owner publication within this single
export for all four actual switches (preemption, block, entry and exit of
idle); checks that slots transferred, owner did not commit, then invokes
the existing combined guarded reverse/ready compensation. It retries only
after verified restoration, and verifies the committed owner/slots and
generation on actual IRETQ task execution. Owner/table alias refusal is
checked before transfer. Both PC and Q35 distinguish omitted frame and
owner calls (H/I) and actual stale-ready fail-stop (Z).
Local 134/134 hardware cases, all 124 inherited rows and inherited object
metadata identical, all inherited host oracles and two empty-PATH builds.
New object/source/text hashes:
- 44230c00c436740015a9713aaf0affe3eaf1bccbdc8521b6796ef2ea93547bf9
- 0d3e6426dd668f4a15c646efa29510c5078052b9900fab8487140a8c0cb61361
- 9308ee7a43b841eab71082e52167c10cec4ef175ce43877ce12cfefb81b3b069

This is fixed BSP/non-nested/caller-owned state, not atomic multiword
transaction, general SMP, or resource authority. Ready selection, retry
and compensation coordination, and EOI still remain externally composed.
No production lock, main, original budget, historical failure, or full
Linux gate change. Independent CI required on the exact new head.
