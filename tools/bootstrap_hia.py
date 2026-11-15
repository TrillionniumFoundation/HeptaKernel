#!/usr/bin/env python3
"""Rebuild the pinned external HIA compiler, retaining each native generation.

The initial B0 bootstrap uses upstream Python and GNU ld. B1, B2 and B3 execute
HIA-generated machine code. The final executable then rebuilds itself twice
with an empty environment except PATH='', before it is used on kernel sources.
This script does not translate, interpret, or implement the kernel allocator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
LOCK = PROJECT / "compatibility/hia-toolchain-lock.json"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(root: Path, *arguments: str) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), *arguments], text=True, timeout=30
    ).strip()


def source_identity(root: Path, lock: dict) -> dict:
    if Path(git(root, "rev-parse", "--show-toplevel")).resolve() != root:
        raise RuntimeError("--root must identify the HIA checkout itself")
    head = git(root, "rev-parse", "HEAD")
    if head != lock["commit"]:
        raise RuntimeError("HIA checkout does not match the locked commit")
    if git(root, "status", "--porcelain", "--untracked-files=all"):
        raise RuntimeError("HIA source checkout must be clean")
    return {"commit": head, "tree": git(root, "rev-parse", "HEAD^{tree}"),
            "worktree_clean": True}


def bootstrap(root: Path, output: Path, report: dict) -> None:
    lock_bytes = LOCK.read_bytes()
    lock = json.loads(lock_bytes)
    if (lock["schema"] != "heptakernel.hia-toolchain-lock.v1"
            or lock["repository"] != "TrillionniumFoundation/Hepta"
            or lock["compiler_source"] != "examples/hia_bootstrap/selfhost.hepta"):
        raise RuntimeError("Unexpected HIA toolchain lock format")
    for field, width in (("commit", 40), ("compiler_source_sha256", 64),
                         ("compiler_sha256", 64), ("B1_B2_B3_sha256", 64)):
        if re.fullmatch("[0-9a-f]{" + str(width) + "}", lock[field]) is None:
            raise RuntimeError("Malformed toolchain identity: " + field)
    if sys.platform != "linux" or platform.machine() not in {"x86_64", "AMD64"}:
        raise RuntimeError("The pinned native bootstrap requires Linux x86-64")
    # B0 is deliberately the reference bootstrap. Optional owner selection would
    # change that boundary and needs a separately qualified recipe.
    if any(key.startswith("HEPTA_HIA_") for key in os.environ):
        raise RuntimeError("Run bootstrap without HEPTA_HIA_ owner selectors")
    identity = source_identity(root, lock)
    source = (root / lock["compiler_source"]).read_bytes()
    if digest(source) != lock["compiler_source_sha256"]:
        raise RuntimeError("HIA compiler source hash differs from its lock")
    report.update(toolchain_lock_sha256=digest(lock_bytes), source=identity,
                  compiler_source_sha256=digest(source))

    sys.dont_write_bytecode = True
    sys.path.insert(0, str(root))
    from tools.qualify_hia_selfhost import build_seed, compile_stage

    image, seed = build_seed(output, source)
    report["B0"] = {"requires_Python": True, "requires_GNU_ld": True,
                    "image_sha256": digest(image.read_bytes()),
                    "receipt": "B0.receipt.json"}
    generations = []
    for label in ("B1", "B2", "B3"):
        image, receipt = compile_stage(
            output, label, image, source,
            image_format="seed-shared" if label == "B1" else "flat-x86-64")
        image_hash = digest(image.read_bytes())
        if image_hash != receipt["produced_sha256"]:
            raise RuntimeError(label + " artifact differs from its native receipt")
        generations.append({"generation": label, "image_sha256": image_hash,
                            "image_bytes": image.stat().st_size,
                            "receipt": label + ".receipt.json"})
        report["native_generations"] = list(generations)
    if {item["image_sha256"] for item in generations} != {lock["B1_B2_B3_sha256"]}:
        raise RuntimeError("B1, B2 and B3 must match each other and the locked image")

    flat_header = b"hia-asm.v1 hepta.hia.program.v8 selfhost\n"
    exec_header = b"hia-asm.v1 hepta.hia.program.v8 selfhost_exec\n"
    if not source.startswith(flat_header):
        raise RuntimeError("Unexpected compiler source module header")
    executable_source = exec_header + source[len(flat_header):]
    compiler, _ = compile_stage(output, "native-compiler", image,
                                executable_source, output_extension="")
    compiler_bytes = compiler.read_bytes()
    if digest(compiler_bytes) != lock["compiler_sha256"]:
        raise RuntimeError("Native compiler differs from the locked executable")
    compiler.chmod(0o755)
    report.update(native_compiler_sha256=digest(compiler_bytes),
                  native_compiler_bytes=len(compiler_bytes))

    previous = compiler
    rebuilds = []
    for generation in (1, 2):
        result = subprocess.run(
            [str(previous)], input=executable_source, capture_output=True,
            timeout=20, cwd=output, env={"PATH": ""})
        if result.returncode != 0 or result.stderr or result.stdout != compiler_bytes:
            raise RuntimeError("Standalone compiler failed to reproduce its exact bytes")
        rebuilt = output / ("native-compiler-rebuilt-" + str(generation))
        with rebuilt.open("xb") as stream:
            stream.write(result.stdout)
        rebuilt.chmod(0o755)
        rebuilds.append({"generation": generation, "sha256": digest(result.stdout),
                         "environment": {"PATH": ""}, "exit_code": result.returncode})
        previous = rebuilt
    report["standalone_rebuilds"] = rebuilds
    if source_identity(root, lock) != identity:
        raise RuntimeError("HIA source checkout changed during the bootstrap")
    if (LOCK.read_bytes() != lock_bytes
            or (root / lock["compiler_source"]).read_bytes() != source
            or compiler.read_bytes() != compiler_bytes):
        raise RuntimeError("Toolchain inputs or final executable changed during readback")
    report.update(status="PASS", full_upstream_cold_qualification=False,
                  compiler_correctness_formally_proved=False,
                  kernel_full_linux_closure=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT / ".toolchain/hepta",
                        help="clean checkout of the exact locked Hepta commit")
    parser.add_argument("--output", type=Path, default=PROJECT / ".toolchain/compiler",
                        help="new directory for the compiler and generation evidence")
    args = parser.parse_args()
    root, output = args.root.resolve(), args.output.resolve()
    # Preserve previous evidence. A retry uses a new output directory.
    output.mkdir(parents=True, exist_ok=False)
    report = {"schema": "heptakernel.hia-bootstrap.v1", "status": "FAIL",
              "source_root": str(root), "output": str(output),
              "python": sys.version, "platform": platform.platform()}
    started = time.monotonic()
    try:
        bootstrap(root, output, report)
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        report["elapsed_seconds"] = time.monotonic() - started
        (output / "bootstrap-report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
