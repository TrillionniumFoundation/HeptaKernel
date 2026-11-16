#!/usr/bin/env python3
"""Lossless, bounded-memory inventory for the pinned Linux git tree.

Host-only audit tooling: NOT a kernel/HIA implementation or closure receipt.
No checkout, network requests, or fallback to HEAD. Exact commit must exist.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess

PINNED = "7595a62d45ee1a2297eafa5f2ef5d0a45142d84d"
KCONFIG_DECL = re.compile(rb"^[ \t]*(config|menuconfig)[ \t]+([A-Za-z0-9_]+)(?:[ \t]|$)")


def git(root: Path, *args: str, binary: bool = False) -> bytes | str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                            timeout=180, check=True)
    return result.stdout if binary else result.stdout.decode("ascii").strip()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_tree(raw: bytes):
    """Parse NUL-delimited git ls-tree output; filenames may contain tabs."""
    for row in raw.split(b"\x00"):
        if not row:
            continue
        header, sep, path = row.partition(b"\t")
        if not sep or not path:
            raise ValueError("Malformed git tree row")
        fields = header.split(b" ")
        if len(fields) != 3:
            raise ValueError("Malformed git tree header")
        mode, kind, oid = fields
        if not re.fullmatch(rb"[0-7]{6}", mode) or kind not in (b"tree", b"blob", b"commit"):
            raise ValueError("Unsupported git entry")
        if not re.fullmatch(rb"[0-9a-f]{40,64}", oid):
            raise ValueError("Malformed git object ID")
        yield mode.decode("ascii"), kind.decode("ascii"), oid.decode("ascii"), path


def collect(root: Path, expected_commit: str, output: Path) -> dict:
    """Fixture-controllable engine; public CLI ALWAYS uses the pinned commit."""
    actual = git(root, "rev-parse", "--verify", expected_commit + "^{commit}")
    if actual != expected_commit:
        raise RuntimeError("Exact commit not present: " + expected_commit)
    root_tree = git(root, "rev-parse", "--verify", expected_commit + "^{tree}")
    raw = git(root, "ls-tree", "-rtz", "--full-tree", expected_commit, binary=True)
    entries = list(parse_tree(raw))
    if not entries or len(set(path for _, _, _, path in entries)) != len(entries):
        raise RuntimeError("Empty or duplicate tracked paths")
    if not any(kind == "tree" for _, kind, _, _ in entries):
        raise RuntimeError("Recursive inventory unexpectedly has no directory")
    output.mkdir(mode=0o755, parents=True, exist_ok=False)
    names = {"tree": 0, "blob": 0, "commit": 0}
    kconfigs, uapi = [], []
    source_families = {}
    compressed = output / "git-tree-entries.jsonl.gz"
    with compressed.open("xb") as sink:
        with gzip.GzipFile(filename="", mode="wb", fileobj=sink, mtime=0, compresslevel=6) as stream:
            for mode, kind, oid, path in entries:
                names[kind] += 1
                top = path.split(b"/")[0].decode("utf-8", "surrogateescape")
                source_families[top] = source_families.get(top, 0) + 1
                record = {"mode": mode, "type": kind, "git_oid": oid,
                          "path_hex": path.hex(), "path": path.decode("utf-8", "backslashreplace")}
                stream.write((json.dumps(record, ensure_ascii=True, sort_keys=True,
                                         separators=(",", ":")) + "\n").encode())
                if kind != "blob":
                    continue
                parts = path.split(b"/")
                if parts[-1].startswith(b"Kconfig"):
                    content = git(root, "cat-file", "blob", oid, binary=True)
                    for line, source in enumerate(content.splitlines(), 1):
                        match = KCONFIG_DECL.match(source)
                        if match:
                            kconfigs.append({"path_hex": path.hex(), "line": line,
                                             "kind": match.group(1).decode(),
                                             "symbol": match.group(2).decode()})
                if (b"include/uapi/" in b"/" + path or path.startswith(b"include/uapi/")):
                    uapi.append({"path_hex": path.hex(), "git_oid": oid})
    kconfigs.sort(key=lambda x: (x["path_hex"], x["line"]))
    uapi.sort(key=lambda x: x["path_hex"])
    for name, data in (("kconfig-symbol-occurrences.json", kconfigs),
                       ("uapi-headers.json", uapi)):
        (output / name).write_text(json.dumps(data, ensure_ascii=True,
                                              separators=(",", ":"), sort_keys=True) + "\n")
    summary = {
        "schema": "heptakernel.pinned-linux-inventory.v1",
        "status": "RAW_TREE_AND_DECLARATIONS_ENUMERATED",
        "pinned_linux_commit": expected_commit, "upstream_tree_sha": root_tree,
        "ls_tree_wire_sha256": sha256(raw), "ls_tree_wire_bytes": len(raw),
        "tracked_entry_count": len(entries), "tracked_counts": names,
        "by_top_level": dict(sorted(source_families.items())),
        "kconfig_symbol_occurrences": len(kconfigs),
        "uapi_header_path_count": len(uapi),
        "artifact_sha256": {name: sha256((output / name).read_bytes()) for name in (
            "git-tree-entries.jsonl.gz", "kconfig-symbol-occurrences.json", "uapi-headers.json")},
        "driver_hardware_ids_complete": False, "generated_uapi_complete": False,
        "linux_behavioral_coverage_complete": False, "full_rewrite_complete": False,
        "limits": ["Git paths captured losslessly as hex, no recursive API truncation",
                   "Kconfig source declarations listed, not fully evaluated for each config",
                   "UAPI paths do not prove struct/ioctl semantics or generated ABI",
                   "Hardware IDs and complete Linux behavior remain unqualified"],
    }
    (output / "summary.json").write_text(json.dumps(summary, sort_keys=True, indent=2) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--linux-git", type=Path, required=True,
                        help="local pinned Linux git object repository")
    parser.add_argument("--output", type=Path, required=True,
                        help="fresh output directory; existing evidence is never overwritten")
    args = parser.parse_args()
    summary = collect(args.linux_git.resolve(), PINNED, args.output.resolve())
    print(json.dumps({"status": summary["status"],
                      "sha": summary["pinned_linux_commit"],
                      "entries": summary["tracked_entry_count"],
                      "output": str(args.output)}))


if __name__ == "__main__":
    main()
