#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Check mechanical prerequisites for complete Linux rewrite review.

Exit 2: HOLD (unfinished obligations or missing evidence).
Exit 1: unreadable/invalid manifest or baseline identity mismatch.
Exit 0: manifest conditions are present; independent review is still required.

This tool checks declarations and evidence files. Closure credit requires each
receipt to be a {path, sha256} object whose digest matches its current bytes;
legacy bare paths remain readable on unfinished rows. This does not establish
Linux compatibility, prove HIA safety, or authenticate a report's conclusions.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

SCHEMA = "heptakernel.linux-coverage.v1"
LINUX_SHA = "7595a62d45ee1a2297eafa5f2ef5d0a45142d84d"
HEPTA_BASELINE_SHA = "f33d8da316de8fdf27b504371f1a5310997ff548"
SCOPE = "entire pinned Linux source and behavior; first x86_64 tranche does not reduce this scope"
GATE_IDS = (
    "scope-source-inventory", "hia-target-purity", "hia-machine-semantics",
    "reproducible-build", "boot-platforms", "memory-management",
    "scheduler-processes", "linux-user-abi", "vfs-filesystems", "block-storage",
    "networking", "drivers-platforms", "security-isolation",
    "concurrency-ordering", "upstream-test-compatibility",
    "whole-system-workloads", "full-hia-closure",
)
# Hash sorted (path, upstream_tree_sha) identities, not editable status fields.
FAMILY_IDENTITIES = {
    "arch": (21, "e99dd00d651c8baa6648d1a3fabdeb81b07ce188c11888e8e7d164f0b9019894"),
    "drivers": (144, "ff21a879633cf954def309a9059e90b385e5cf3026568bd5432d60e7dd80ca45"),
    "fs": (76, "f37815fcdaf37f9a7ba0d926b8e123719e6a9129e6e6b5e769067a7cfe1c4547"),
    "net": (66, "ee0c6b644ce38e889565d410f7cb4c36a7021f9d5cfbf47f3a17bc6c3bebad20"),
    "security": (13, "67019070e63506400338339aaaf48e5fd1d1b9f41f9ef4f62a1cc3a25d1babd5"),
    "kernel": (22, "7f539d5d5d2e5ed8b08b25a8c705ad72a178c5674b09baa9edb69271cd36a55d"),
    "mm": (5, "e9a07404f2012dc77b08b1249f4627ff7ceeb60a7c3ead1fbe092d83232405ee"),
}
SYSCALL_COUNT = 422
SYSCALL_IDENTITIES = "ef2d9eee05c035d8a0dcbe84f8cec8753df839e3e46f320592ef797702c7f1ba"
STATES = {
    "NOT_IMPLEMENTED", "IN_PROGRESS", "IMPLEMENTED_UNVERIFIED",
    "VERIFIED_SCOPE", "FAILED", "BLOCKED", "NOT_APPLICABLE_WITH_EVIDENCE",
}
# These are descriptions/data, not instructions executed by the target CPU.
NONEXECUTABLE_SUFFIXES = {
    ".ld", ".md", ".rst", ".txt", ".json", ".toml", ".yaml", ".yml", ".csv", ".tbl",
}
LIMITATION = (
    "This checks manifest structure, fixed baseline identities, local evidence "
    "availability and matching evidence digests, and declared target-source "
    "language. A ready result does not "
    "prove the evidence claims, full Linux compatibility or HIA semantic safety; "
    "independent review of the exact candidate remains required."
)


class ManifestError(ValueError):
    pass


def need(condition, message):
    if not condition:
        raise ManifestError(message)


def canonical_sha(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, "duplicate JSON object member: " + key)
        result[key] = value
    return result


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repository_path(root, value):
    need(isinstance(value, str) and value.strip(), "empty or non-string evidence/source path")
    rel = Path(value)
    need(not rel.is_absolute() and ".." not in rel.parts,
         "evidence/source paths must stay relative to the repository")
    resolved = (root / rel).resolve()
    need(resolved.is_relative_to(root), "evidence/source symlink leaves repository")
    return resolved


def evidence_ready(root, items, *, require_pins=False):
    need(isinstance(items, list), "evidence must be an array")
    ready = bool(items)
    for item in items:
        if isinstance(item, str):
            path = repository_path(root, item)
            expected = None
        else:
            need(isinstance(item, dict), "evidence item must be a path or {path, sha256}")
            path = repository_path(root, item.get("path"))
            expected = item.get("sha256")
            need(isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected),
                 "evidence object requires a lowercase SHA-256")
        if not path.is_file() or path.stat().st_size == 0:
            ready = False
        elif expected is None:
            # Historical path-only receipts stay readable on unfinished rows
            # but may not be used to remove a closure obligation.
            if require_pins:
                ready = False
        elif file_sha256(path) != expected:
            ready = False
    return ready


def paths_ready(root, values):
    need(isinstance(values, list), "implementation_paths must be an array")
    ready = bool(values)
    for value in values:
        path = repository_path(root, value)
        if not path.is_file() or path.stat().st_size == 0:
            ready = False
    return ready


def row_ready(root, row, *, kind):
    need(isinstance(row, dict), "obligation must be an object")
    status = row.get("status")
    need(isinstance(status, str) and status in STATES, "unknown obligation status")
    claims_credit = status in {"VERIFIED_SCOPE", "NOT_APPLICABLE_WITH_EVIDENCE"}
    evidence_ok = evidence_ready(root, row.get("evidence"), require_pins=claims_credit)
    implementation_ok = paths_ready(root, row.get("implementation_paths"))
    if status == "NOT_APPLICABLE_WITH_EVIDENCE":
        # Only an explicitly obsolete/unimplemented upstream syscall can take
        # this path. The upstream source note and the decision both need records.
        obsolete = (kind == "syscall" and
                    row.get("baseline_behavior") ==
                    "UPSTREAM_UNIMPLEMENTED_OR_OBSOLETE_REQUIRES_MATCHING_ERRNO" and
                    row.get("entry") in (None, "sys_ni_syscall"))
        baseline_ok = evidence_ready(root, row.get("baseline_evidence", []), require_pins=True)
        return bool(obsolete and evidence_ok and baseline_ok)
    if status != "VERIFIED_SCOPE":
        return False
    if kind == "gate":
        return evidence_ok
    if kind == "syscall" and row.get("entry") in (None, "sys_ni_syscall"):
        return evidence_ok
    return evidence_ok and implementation_ok


def inspect(manifest, root):
    need(isinstance(manifest, dict), "manifest must be an object")
    need(manifest.get("schema") == SCHEMA, "unexpected coverage schema")
    need(manifest.get("scope") == SCOPE, "full Linux target scope changed")
    baseline = manifest.get("baseline")
    need(isinstance(baseline, dict), "missing baseline")
    need(baseline.get("linux_version") == "7.3.4" and
         baseline.get("linux_commit") == LINUX_SHA, "Linux baseline changed")
    need(baseline.get("hepta_commit") == HEPTA_BASELINE_SHA, "Hepta baseline changed")
    for flag in ("inventory_complete", "full_rewrite_complete"):
        need(type(manifest.get(flag)) is bool, flag + " must be a boolean")

    gates = manifest.get("gates")
    need(isinstance(gates, list), "gates must be an array")
    need(all(isinstance(g, dict) and isinstance(g.get("id"), str) for g in gates),
         "gate identity missing")
    counts = Counter(g["id"] for g in gates)
    need(set(counts) == set(GATE_IDS) and all(n == 1 for n in counts.values()),
         "the fixed 17 gate IDs must each occur exactly once")
    gate_pending = [g["id"] for g in gates if not row_ready(root, g, kind="gate")]

    families = manifest.get("source_family_obligations")
    need(isinstance(families, dict) and set(families) == set(FAMILY_IDENTITIES),
         "source-family inventory keys changed")
    family_pending = {}
    for family, (expected_count, expected_hash) in FAMILY_IDENTITIES.items():
        rows = families[family]
        need(isinstance(rows, list) and len(rows) == expected_count,
             family + " source-family count changed")
        need(all(isinstance(r, dict) and isinstance(r.get("path"), str) and
                 isinstance(r.get("upstream_tree_sha"), str) for r in rows),
             family + " source-family identity missing")
        identities = sorted((r["path"], r["upstream_tree_sha"]) for r in rows)
        need(canonical_sha(identities) == expected_hash,
             family + " source-family identities changed")
        family_pending[family] = sum(not row_ready(root, r, kind="source") for r in rows)

    syscalls = manifest.get("x86_64_syscall_table")
    need(isinstance(syscalls, list) and len(syscalls) == SYSCALL_COUNT,
         "x86 syscall table must preserve all 422 baseline rows")
    keys = ("number", "abi", "name", "entry", "extra", "baseline_behavior")
    need(all(isinstance(r, dict) and all(k in r for k in keys) for r in syscalls),
         "syscall identity missing")
    identities = sorted([{k: r[k] for k in keys} for r in syscalls],
                        key=lambda r: (r["number"], r["abi"]))
    need(canonical_sha(identities) == SYSCALL_IDENTITIES, "x86 syscall identities changed")
    syscall_pending = sum(not row_ready(root, r, kind="syscall") for r in syscalls)

    non_hia = []
    target_directories_missing = []
    hia_sources = 0
    for dirname in ("src", "arch"):
        directory = root / dirname
        if not directory.is_dir():
            target_directories_missing.append(dirname)
            continue
        for path in sorted(directory.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(root).as_posix()
            need(path.resolve().is_relative_to(root), "target source symlink leaves repository")
            if path.suffix == ".hepta":
                if path.read_bytes().startswith(b"hia-asm.v1 "):
                    hia_sources += 1
                else:
                    non_hia.append(relative + " (missing HIA source header)")
            elif path.suffix.lower() not in NONEXECUTABLE_SUFFIXES:
                non_hia.append(relative)

    flags_pending = [key for key in ("inventory_complete", "full_rewrite_complete")
                     if not manifest[key]]
    ready = not (flags_pending or gate_pending or any(family_pending.values()) or
                 syscall_pending or non_hia or target_directories_missing or not hia_sources)
    return {
        "schema": "heptakernel.closure-check.v1",
        "status": "MANIFEST_READY_FOR_INDEPENDENT_REVIEW" if ready else "HOLD",
        "mechanical_conditions_complete": ready,
        "independently_qualified": False,
        "linux_version": "7.3.4",
        "linux_commit": LINUX_SHA,
        "flags_pending": flags_pending,
        "gate_ids_pending": gate_pending,
        "pending_counts": {"gates": len(gate_pending), "source_families": family_pending,
                           "x86_syscall_rows": syscall_pending},
        "non_hia_target_sources": non_hia,
        "target_directories_missing": target_directories_missing,
        "hia_source_count": hia_sources,
        "limitation": LIMITATION,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    manifest_path = args.manifest or root / "compatibility/coverage.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
        report = inspect(manifest, root)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"schema": "heptakernel.closure-check.v1", "status": "INVALID_MANIFEST",
                          "error": str(exc), "independently_qualified": False,
                          "limitation": LIMITATION}, sort_keys=True))
        return 1
    print(json.dumps(report, sort_keys=True))
    return 0 if report["mechanical_conditions_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

