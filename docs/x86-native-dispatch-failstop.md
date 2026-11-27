# Experimental native dispatch fatal trap (HOLD)

This candidate builds on the exact terminal-dispatch implementation at 6cc01b1bca8755ceb1c508087e36a4abbf2c7f7b. It adds an HIA wrapper that invokes the existing terminal dispatch logic and returns only the explicitly recoverable results 0, 64, 65, 66, and 69. Every other result executes the native HIA user trap. In particular, incomplete ready compensation (67), unknown partial state (70), and post-commit EOI failure (71) must never return to the dispatch caller. This is a fail-stop boundary, not a rollback of already committed ownership and not an automatic retry.

The PC and Q35 QEMU observers check successful short and long dispatch and recoverable owner refusal, and independently verify the native UD2 exception RIP, disabled interrupts, ISR, ready word, owner, frame slots, and target progress for the three fatal paths. Fault variants induce a stale ready expectation, a stale rollback owner after forward transfer, and a failed EOI. A separate trap-bypass control returns instead of trapping and is detected by N. The observer's precise exception address is bound to the actual native bytes; the inherited cases and object reports must remain identical.

Desktop qualification: 170/170 cases passed, including all 156 inherited cases byte-for-byte in the case report and 14 additional cases. Initial r1 source failed compilation due to duplicate SSA names and was retained locally; r2 corrected the names and passed. Native source/object/text hashes:
- source: 7b3271f0d3683228ffe7d622fbf2d7e7eb5e3119ae083eb7fab3228146dc2d0a
- object: 68cc85653e171e0e4a47002ba23f2923a71cc5e8a0ad132067990926b2870711
- text: 4db68f91a070aea8be713998718cb323bc9031722e9ddf6ee81872c33e8d32d4

This is an experimental BSP dispatch qualification, not general Linux acceptance. Production panic/exception routing, resource ownership, arbitrary CPU/SMP dispatch, synchronous sleep/wake, native HLT, all architecture/ABI/driver coverage, historical failures, the original 3s/5s/60s gates, the 17 HOLD gates and 422 syscall obligations remain open and unchanged. The trap prevents a normal return; it does not by itself prove a production exception handler cannot resume. No production main or lock is changed.
