# Experimental native ready exchange (HOLD)

Parent: #205, 0d6491c4eba3af7bd2abee124cadceb5a23d2172. A running task is excluded from a 32-bit ready mask. If its quantum expires and it remains runnable, select the next ready task and atomically replace that task's bit with the outgoing task's bit in the same 64-bit generation-incrementing CAS. No intermediate state loses the runnable outgoing task. If the ready mask is empty, validate the complete live word with identity CAS and return the current task without changing generation. Invalid input (including current already ready, out-of-range bits, generation exhaustion) returns 65; a failed live-word comparison returns 66. The current task's identity and authority are caller obligations. This is not task blocking, task ownership, frame transfer, or a complete preemption transaction. The independent 64-task selector and all prior gates remain unchanged.

Local qualification on exact experimental compiler 970a16f48687678c0df1b307a987ef9651d81481c70563af1cf4c92c536a70f4:
- 49,322 sequential native calls, 2,108 native rotations, 128 concurrent races against the actual #205 native publisher; each race checks the whole resulting word against one of two valid serialized outcomes.
- Five compiled negative controls detected. Two empty-PATH builds identical.
- Initial generated candidate rejected with exit 2; removed unreachable f0 idle block, then reran all tests in a new output directory. Initial source SHA256 c361da08d57918e03a6db0e54cc167728d546863fd7bad5ac3b63cee90df3858. Original failure retained locally.
- Final source SHA256 e3ba0cf8e07a1011b617a2117e991d8d09361ef0bcfd56a632dce5b6818d83f8, object 90c793a1e883c04157366e0ef2f6bc210afea7b32d8397c5f811b9b664a1c2a1.
- Publisher object fc4377904d2fc5bb33e5a49033c01336c10555932b6939c2b3930cde216a5487 matches #205 independent CI.
- #205 independent CI 45613381602 passed. Earlier intermittent inherited IRQ/frame-handoff failures remain open.

Independent CI pending. No production lock, coverage, original test, or main change. All original Linux acceptance obligations remain open.
