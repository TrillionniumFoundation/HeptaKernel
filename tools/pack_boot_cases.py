#!/usr/bin/env python3
"""Pack independent requests and expected results; never generate HIA source."""
import json
import struct
import sys
from pathlib import Path

source, output = map(Path, sys.argv[1:])
data = json.loads(source.read_text())
if data["schema"] != "heptakernel.boot-cases.v1" or not data["cases"]:
    raise SystemExit("invalid boot fixtures")
chunks = []
for case in data["cases"]:
    if len(case["request"]) != 4 or len(case["expected"]) != 2:
        raise SystemExit("invalid boot case: " + case["name"])
    chunks.append(struct.pack("<6Q", *case["request"], *case["expected"]))
output.write_bytes(b"".join(chunks))
