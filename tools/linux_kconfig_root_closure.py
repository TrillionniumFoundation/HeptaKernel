#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Conservative root traversal of immutable Linux Kconfig include candidates.

This is a *profiled lexical* root closure, NOT the evaluated Kconfig graph.
It follows only tracked regular-file literal edges in the Git object ledger;
it never executes Kconfig, follows symlinks, or silently resolves variables.
Conditional includes may be inactive; help/continuation lines are retained
but excluded from traversal. Every original lexical edge stays in the output.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter, deque
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

# -I excludes the script directory: explicitly load only this sibling module.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from linux_kconfig_include_targets import decode, encode, literal_target

VAR = re.compile(rb"\$\((SRCARCH|HEADER_ARCH)\)|\$\{(SRCARCH|HEADER_ARCH)\}|\$(SRCARCH|HEADER_ARCH)\b")
SAFE_ARCH = re.compile(r"[a-z0-9_]+\Z")
KINDS = {"source", "rsource", "osource", "orsource"}
FOLLOW = "TRACKED_REGULAR_LITERAL"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def jsonl(rows: list[dict]) -> bytes:
    return b"".join((json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
                    for r in rows)


def expand_operand(operand: bytes, bindings: dict[str, str]) -> tuple[bytes, bool]:
    """Replace only explicitly supplied SRCARCH/HEADER_ARCH identifiers.

    An unsupported expression remains unresolved by literal_target. Neither
    env vars nor the host filesystem are consulted. The return flag means
    at least one supported variable was actually substituted.
    """
    changed = False

    def substitute(match: re.Match[bytes]) -> bytes:
        nonlocal changed
        key = next(value for value in match.groups() if value is not None).decode("ascii")
        changed = True
        return bindings[key].encode("ascii")

    return VAR.sub(substitute, operand), changed


def projection(paths: dict[bytes, dict], rows: list[dict],
               bindings: dict[str, str], root: bytes = b"Kconfig"):
    """Build reproducible, possibly-inactive paths from one explicit root."""
    if set(bindings) != {"SRCARCH", "HEADER_ARCH"} or any(
            not isinstance(v, str) or not SAFE_ARCH.fullmatch(v)
            for v in bindings.values()):
        raise ValueError("require explicit safe SRCARCH and HEADER_ARCH profile")
    entry = paths.get(root)
    if entry is None or entry.get("mode") not in ("100644", "100755") or entry.get("type") != "blob":
        raise ValueError("Kconfig root must be a tracked regular Git blob")
    edges: dict[bytes, list[int]] = {}
    enriched = []
    for index, row in enumerate(rows):
        path = decode(row["path_b64"])
        if path not in paths or paths[path]["oid"] != row["blob_oid"]:
            raise ValueError("unbound original Kconfig edge")
        if row["kind"] not in KINDS or row["source_context"] not in (
                "DIRECTIVE_LEXICAL_CANDIDATE", "HELP_TEXT_LEXICAL_ONLY",
                "UNRESOLVED_PHYSICAL_CONTINUATION", "UNRESOLVED_MIXED_HELP_INDENTATION"):
            raise ValueError("invalid lexical edge kind/context")
        operand = decode(row["operand_b64"])
        raw_status, raw_path, raw_hit = literal_target(path, row["kind"], operand, paths)
        if (raw_status != row["resolution"]
                or (encode(raw_path) if raw_path is not None else None) != row["target_path_b64"]
                or (raw_hit["oid"] if raw_hit is not None else None) != row["target_oid"]
                or (raw_hit["mode"] if raw_hit is not None else None) != row["target_mode"]):
            raise ValueError("forged or stale literal target projection")
        expanded, changed = expand_operand(operand, bindings)
        status, target, hit = literal_target(path, row["kind"], expanded, paths)
        new = {**row, "profile_resolution": status,
               "profile_target_path_b64": encode(target) if target is not None else None,
               "profile_target_oid": hit["oid"] if hit is not None else None,
               "profile_source": "EXPLICIT_VARIABLE_BINDING" if changed else "ORIGINAL_LITERAL"}
        enriched.append(new)
        edges.setdefault(path, []).append(index)

    seen: dict[bytes, tuple[int, bytes | None, int | None]] = {root: (0, None, None)}
    todo = deque([root])
    while todo:
        parent = todo.popleft()
        depth = seen[parent][0]
        for index in edges.get(parent, []):
            row = enriched[index]
            if (row["source_context"] != "DIRECTIVE_LEXICAL_CANDIDATE"
                    or row["profile_resolution"] != FOLLOW):
                continue
            target = decode(row["profile_target_path_b64"])
            if target not in seen:
                seen[target] = (depth + 1, parent, row["line"])
                todo.append(target)

    counts = Counter()
    for row in enriched:
        parent = decode(row["path_b64"])
        if parent not in seen:
            route = "SOURCE_NOT_REACHED"
        elif row["source_context"] != "DIRECTIVE_LEXICAL_CANDIDATE":
            route = "NON_DIRECTIVE_CONTEXT"
        elif row["profile_resolution"] == FOLLOW:
            route = "FOLLOWED_TRACKED_FILE"
        else:
            route = "REACHED_UNRESOLVED_OR_UNFOLLOWABLE"
        row["root_route"] = route
        row["root_parent_depth"] = seen[parent][0] if parent in seen else None
        counts[route] += 1

    files = [
        {"path_b64": encode(path), "oid": paths[path]["oid"], "depth": value[0],
         "first_parent_b64": encode(value[1]) if value[1] is not None else None,
         "first_parent_line": value[2]}
        for path, value in sorted(seen.items())
    ]
    if sum(counts.values()) != len(rows) or len(files) != len(seen):
        raise ValueError("incomplete root traversal")
    return enriched, files, dict(sorted(counts.items()))


def build(repo: Path, inventory: Path, srcarch: str, header_arch: str):
    base = json.loads((inventory / "report.json").read_bytes())
    literals = json.loads((inventory / "kconfig-literal-targets-report.json").read_bytes())
    sources = (inventory / "source-paths.jsonl").read_bytes()
    edges = (inventory / "kconfig-literal-targets.jsonl").read_bytes()
    if (base["linux_commit"] != literals["linux_commit"]
            or base["linux_root_tree"] != literals["linux_root_tree"]
            or digest(sources) != base["source_paths_sha256"]
            or digest(sources) != literals["upstream_paths_sha256"]
            or digest(edges) != literals["source_sha256"]
            or literals["upstream_edges_sha256"] != base["kconfig_source_edges_sha256"]
            or literals["status"] != "PARTIAL_LITERAL_TARGETS_NOT_ACTIVE_KCONFIG_GRAPH"):
        raise ValueError("unbound or tampered pinned Kconfig ledgers")
    expected = base["linux_commit"]
    head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], timeout=30).strip().decode()
    tree = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"], timeout=30).strip().decode()
    if head != expected or tree != base["linux_root_tree"]:
        raise ValueError("Linux Git commit/tree differs from fixed inventory")
    paths: dict[bytes, dict] = {}
    for raw in sources.splitlines():
        record = json.loads(raw)
        path = decode(record["path_b64"])
        if not path or path in paths:
            raise ValueError("missing/duplicate tracked path")
        paths[path] = record
    rows = list(map(json.loads, edges.splitlines()))
    if len(paths) != base["counts"]["tracked_paths"] or len(rows) != literals["counts"]["all_lexical_edges"]:
        raise ValueError("ledger row count mismatch")
    bindings = {"SRCARCH": srcarch, "HEADER_ARCH": header_arch}
    projected, reached, counts = projection(paths, rows, bindings)
    projected_data, reached_data = jsonl(projected), jsonl(reached)
    if subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], timeout=30).strip().decode() != expected:
        raise ValueError("Linux HEAD moved during root traversal")
    report = {
        "schema": "heptakernel.linux-kconfig-profiled-root.v1",
        "status": "PARTIAL_POSSIBLE_ROOT_GRAPH_NOT_EVALUATED_KCONFIG",
        "linux_commit": expected, "linux_root_tree": tree,
        "root_path_b64": encode(b"Kconfig"), "profile": bindings,
        "source_literal_sha256": digest(edges),
        "source_paths_sha256": digest(sources),
        "profile_edges_sha256": digest(projected_data),
        "reachable_files_sha256": digest(reached_data),
        "counts": {**counts, "all_lexical_edges": len(projected),
                   "reachable_regular_files": len(reached)},
        "inventory_complete": False, "full_rewrite_complete": False,
        "limitations": [
            "Overapproximates conditional literal include activation and may underapproximate unresolved syntax",
            "Profile bindings are caller-selected, not derived from an evaluated Linux configuration",
            "No macros beyond exact SRCARCH/HEADER_ARCH, globbing, shell execution or symlink traversal",
            "Help/continuation/mixed physical contexts are not followed, but all raw rows are retained",
            "No Kconfig symbol semantics, generated build paths, driver behavior or kernel code qualification",
        ],
    }
    return projected_data, reached_data, report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--srcarch", required=True)
    parser.add_argument("--header-arch", required=True)
    args = parser.parse_args()
    edges, files, report = build(args.repo, args.inventory, args.srcarch, args.header_arch)
    args.inventory.mkdir(parents=True, exist_ok=True)
    (args.inventory / "kconfig-profile-root-edges.jsonl").write_bytes(edges)
    (args.inventory / "kconfig-profile-root-files.jsonl").write_bytes(files)
    (args.inventory / "kconfig-profile-root-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
