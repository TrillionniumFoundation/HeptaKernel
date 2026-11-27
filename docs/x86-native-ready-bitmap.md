# Experimental native ready bitmap selection
The scalar HIA export f0 takes a 64-bit readiness bitmap, task count 1..64,
and current task index. It scans circularly starting after the current index;
64 denotes no ready task, 65 denotes invalid input. The current task is
eligible after one complete cycle. Width 64 is handled without shifting by
64. The scan consumes at most count probes, and a stable nonempty bitmap
visits each ready task once per cycle.

Local qualification used the exact experimental compiler SHA256
970a16f48687678c0df1b307a987ef9651d81481c70563af1cf4c92c536a70f4.
Two empty-PATH compilations gave identical objects; independent host
oracle checked 385614 native calls, including every bitmap for widths 1..12,
64-bit boundary cases, deterministic random masks and stable-mask fairness.
Three compiled semantic mutations were detected. An earlier mutation
created unreachable blocks and was refused by the compiler; the final
mutations preserve the CFG. Independent CI remains required.

This is a pure selector, not live task admission, runqueue authority,
multitask context switching or SMP. Bitmap/cursor ownership and coherent
snapshot publication are caller responsibilities. No original acceptance
gates, syscall rows, production lock or main branch changes.
