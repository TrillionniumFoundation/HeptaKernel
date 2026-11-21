#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Possible root Kconfig include reachability for every pinned architecture directory.

The profiles bind SRCARCH=HEADER_ARCH to each directory *name*, not to a
Kbuild-evaluated environment. They are lexical upper bounds with unresolved
variables, conditional branches and optional includes explicitly retained.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from linux_kconfig_include_targets import decode, encode
from linux_kconfig_root_closure import build, digest, jsonl

ARCH = re.compile(r"[a-z0-9_]+\Z")


def assemble(profiles: list[tuple[str, bytes, bytes, dict]]) -> tuple[bytes, bytes, list[dict], dict]:
    """Join byte-preserving per-profile reachability without treating it as active Kconfig."""
    membership: list[dict] = []
    union: dict[bytes, dict] = {}
    summaries: list[dict] = []
    used: set[str] = set()
    source_identity: tuple[str, str, str, str] | None = None
    for arch, edges, files, report in profiles:
        if not isinstance(arch, str) or not ARCH.fullmatch(arch) or arch in used:
            raise ValueError("invalid or duplicate architecture profile")
        used.add(arch)
        identity = (report["linux_commit"], report["linux_root_tree"],
                    report["source_literal_sha256"], report["source_paths_sha256"])
        if source_identity is None:
            source_identity = identity
        if identity != source_identity or report["profile"] != {
                "SRCARCH": arch, "HEADER_ARCH": arch}:
            raise ValueError("inconsistent source identity or profile")
        if (report["profile_edges_sha256"] != digest(edges)
                or report["reachable_files_sha256"] != digest(files)
                or report["counts"]["all_lexical_edges"] != len(edges.splitlines())
                or report["status"] != "PARTIAL_POSSIBLE_ROOT_GRAPH_NOT_EVALUATED_KCONFIG"
                or report["inventory_complete"] or report["full_rewrite_complete"]):
            raise ValueError("unbound or falsely closed profile evidence")
        seen: set[bytes] = set()
        for line in files.splitlines():
            item = json.loads(line)
            path = decode(item["path_b64"])
            if not path or path in seen or item["depth"] < 0:
                raise ValueError("duplicate or malformed profile file")
            seen.add(path)
            original = union.setdefault(path, {"path_b64": encode(path),
                                                 "oid": item["oid"], "arch_profiles": []})
            if original["oid"] != item["oid"]:
                raise ValueError("physical Git blob identity changed between profiles")
            original["arch_profiles"].append(arch)
            membership.append({"arch_profile": arch, **item})
        if b"Kconfig" not in seen or len(seen) != report["counts"]["reachable_regular_files"]:
            raise ValueError("missing root or truncated profile files")
        summaries.append({
            "arch_profile": arch, "profile_edges_sha256": digest(edges),
            "profile_files_sha256": digest(files), "reachable_files": len(seen),
            "route_counts": {key: value for key, value in report["counts"].items()
                             if key != "all_lexical_edges"},
            "lexical_edges": report["counts"]["all_lexical_edges"]})
    if not used:
        raise ValueError("empty profile matrix")
    combined = jsonl(membership)
    united = jsonl([union[key] for key in sorted(union)])
    counts = {"architecture_profiles": len(used),
              "membership_rows": len(membership),
              "union_reachable_files": len(union),
              "intersection_reachable_files": sum(
                  len(value["arch_profiles"]) == len(used) for value in union.values())}
    return combined, united, summaries, counts


def run(repo: Path, inventory: Path, lock_path: Path) -> dict:
    lock = json.loads(lock_path.read_bytes())
    arches = lock["inventories"]["arch_directories"]
    if (not isinstance(arches, list) or len(arches) != 21
            or len(set(arches)) != len(arches)
            or any(not isinstance(a, str) or not ARCH.fullmatch(a) for a in arches)
            or "x86" not in arches):
        raise ValueError("pinned architecture directory inventory changed")
    original = json.loads((inventory / "kconfig-profile-root-report.json").read_bytes())
    profiles = []
    for arch in arches:
        edges, files, report = build(repo, inventory, arch, arch)
        if report["linux_commit"] != lock["linux"]["commit"]:
            raise ValueError("Linux lock differs from inventory commit")
        if arch == "x86":
            if (original["profile"] != report["profile"]
                    or original["profile_edges_sha256"] != digest(edges)
                    or original["reachable_files_sha256"] != digest(files)):
                raise ValueError("cross-profile x86 projection disagrees with existing root audit")
        profiles.append((arch, edges, files, report))
    membership, union, summaries, counts = assemble(profiles)
    report = {
        "schema": "heptakernel.linux-kconfig-arch-matrix.v1",
        "status": "PARTIAL_LEXICAL_ARCH_ROOT_REACHABILITY_NOT_EVALUATED",
        "linux_commit": lock["linux"]["commit"],
        "linux_root_tree": profiles[0][3]["linux_root_tree"],
        "source_literal_sha256": profiles[0][3]["source_literal_sha256"],
        "source_paths_sha256": profiles[0][3]["source_paths_sha256"],
        "membership_sha256": digest(membership), "union_sha256": digest(union),
        "counts": counts, "profiles": summaries,
        "inventory_complete": False, "full_rewrite_complete": False,
        "limitations": [
            "Each source/headers profile uses an architecture directory label, not a Kbuild-derived environment",
            "Conditional includes may be inactive; unresolved expressions may exclude real dependencies",
            "No symlinks, generated configuration, Kconfig conditions or macros are evaluated",
            "Neither Linux functionality nor HIA native instruction support is implemented",
        ],
    }
    (inventory / "kconfig-arch-matrix-memberships.jsonl").write_bytes(membership)
    (inventory / "kconfig-arch-matrix-union.jsonl").write_bytes(union)
    (inventory / "kconfig-arch-matrix-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--lock", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(run(args.repo, args.inventory, args.lock), sort_keys=True))


if __name__ == "__main__":
    main()
