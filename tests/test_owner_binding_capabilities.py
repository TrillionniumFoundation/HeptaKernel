#!/usr/bin/env python3
"""Verify the pinned native HIA checker refuses writes through PMM readbuf."""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/owner_binding.hepta"
LOAD = "  ob_check_byte:u8 = buffer.load(ob_check_state,ob_check_at)"
INJECTION = (
    '  ob_check_mutation_value:u8 = const() {"value":1}\n'
    "  _ = buffer.store(ob_check_state,ob_check_at,ob_check_mutation_value)\n"
    + LOAD
)


def compile_source(compiler: Path, data: str) -> tuple[bool, str]:
    result = subprocess.run([str(compiler)], input=data.encode(), capture_output=True,
                            timeout=30, cwd=ROOT, env={"PATH": ""})
    is_object = result.returncode == 0 and result.stdout.startswith(b"\x7fELF\x02\x01")
    return is_object, hashlib.sha256(result.stdout).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("compiler")
    args = parser.parse_args()
    binary = shutil.which(args.compiler)
    if binary is None:
        raise SystemExit("Pinned HIA compiler not available")
    compiler = Path(binary).resolve()
    source = SOURCE.read_text()
    assert source.count(LOAD) == 1
    assert "fn owner_binding(request:readbuf,reply:mutbuf,state:readbuf)" in source
    assert "fn bitmap_consistent(state:readbuf" in source
    assert "fn read_state_u64(bytes:readbuf" in source

    names = set(re.findall(r"\b([A-Za-z_]\w*):readbuf\b", source))
    state_names = {name for name in names if name == "state"
                   or name == "ob_memory" or name.endswith("_state")}
    assert len(state_names) >= 12, state_names
    for name in state_names:
        assert not re.search(r"\b" + re.escape(name) + r":mutbuf\b", source)

    # Same injected state write is legal with mutbuf and forbidden with readbuf.
    # This actually runs the locked native verifier; it is not a regex-only check.
    invalid = source.replace(LOAD, INJECTION)
    positive = invalid
    for name in state_names:
        positive = re.sub(r"\b" + re.escape(name) + r":readbuf\b",
                          name + ":mutbuf", positive)
    a = positive.index("fn read_state_u64(")
    b = positive.index("end\nfn write_u64(", a)
    positive = positive[:a] + positive[a:b].replace(":readbuf", ":mutbuf") + positive[b:]
    accepted, positive_hash = compile_source(compiler, positive)
    assert accepted, "positive mutbuf state-write control did not compile"
    rejected, negative_hash = compile_source(compiler, invalid)
    assert not rejected, "native HIA verifier accepted a state store through readbuf"
    print({"scope": "HIA PMM binding native capability enforcement",
           "mutbuf_store_compiled": accepted,
           "readbuf_store_rejected": not rejected,
           "positive_object_sha256": positive_hash,
           "negative_output_sha256": negative_hash,
           "linux_full_closure": False})


if __name__ == "__main__":
    main()
