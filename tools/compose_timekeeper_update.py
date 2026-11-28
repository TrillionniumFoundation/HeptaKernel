#!/usr/bin/env python3
"""Compose the pinned clocksource arithmetic with a new single-owner HIA entry."""
from hashlib import sha256
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PROFILE = "hia-asm.v1 hepta.hia.program.v8 selfhost_elf\n"
DELTA = "992bf0331c236d413ce34b51218110cdc6ba6f41b6a9f862c6cfa7cd69b6ae33"


def compose():
    delta = (ROOT / "src/clocksource_delta.hepta").read_bytes()
    if sha256(delta).hexdigest() != DELTA:
        raise ValueError("clocksource parent bytes do not match the reviewed composition")
    parent = delta.decode()
    update = (ROOT / "src/timekeeper_update.hepta").read_text()
    if not update.startswith(PROFILE) or not parent.startswith(PROFILE):
        raise ValueError("HIA profile mismatch")
    # Reuse the entire exact typed validation, modular/limb arithmetic and
    # output flow. The parent's separate raw request decoder isn't needed by
    # this entry. Supply the decoded arguments from update's state and request.
    arithmetic = parent.split("  zero:u64 = const()", 1)[1]
    arithmetic, helpers = arithmetic.split("\nfn read_u64(", 1)
    convert = (
        "fn clock_convert_fields(c_req:readbuf,d_out:mutbuf,c_mem:mutbuf) "
        "-> (u32) effects(read,write,trap) entry(start)\n"
        "block start(c_req:readbuf,d_out:mutbuf,c_mem:mutbuf)\n"
        '  cf0:usize = const() {"value":0}\n'
        '  cf8:usize = const() {"value":8}\n'
        '  cf32:usize = const() {"value":32}\n'
        '  cf40:usize = const() {"value":40}\n'
        '  cf48:usize = const() {"value":48}\n'
        '  cf56:usize = const() {"value":56}\n'
        '  now:u64 = call(c_req,cf8) {"function":"read_u64"}\n'
        '  prior:u64 = call(c_mem,cf0) {"function":"state_u64"}\n'
        '  fraction:u64 = call(c_mem,cf8) {"function":"state_u64"}\n'
        '  mask:u64 = call(c_mem,cf32) {"function":"state_u64"}\n'
        '  limit:u64 = call(c_mem,cf40) {"function":"state_u64"}\n'
        '  mult:u64 = call(c_mem,cf48) {"function":"state_u64"}\n'
        '  shift:u64 = call(c_mem,cf56) {"function":"state_u64"}\n'
        "  zero:u64 = const()" + arithmetic
    )
    # Reuse the exact parent byte decoder with a mutable buffer.
    # Reuse the byte decoder on a mutable borrowed buffer without a cast or
    # a hardware load not accounted for by the verified HIA profile.
    read_block = helpers.split("\nfn write_u64(", 1)[0]
    state_reader = "fn state_u64(" + read_block.replace(":readbuf", ":mutbuf")
    return update + convert + "\nfn read_u64(" + helpers + state_reader + "\n"


if __name__ == "__main__":
    sys.stdout.write(compose())
