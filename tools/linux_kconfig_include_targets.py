#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Resolve only literal Kconfig include targets in the pinned immutable Git tree.

A tracked target is not an active include. Environment variables, globs,
conditional branches, macro expansion, symlinks and help text are not evaluated.
Every original lexical edge is retained, including unresolvable edges.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import hashlib
import json
import posixpath
from pathlib import Path
import re
import subprocess

SOURCE = re.compile(rb"^[ \t]*(source|rsource|osource|orsource)[ \t]+(.+?)[ \t]*$")
SHA1 = re.compile(r"[0-9a-f]{40}\Z")
DYNAMIC = b"$*?[]\\"


def git(repo: Path, *arguments: str) -> bytes:
    return subprocess.run(["git", "--no-replace-objects", "-C", str(repo), *arguments], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def decode(value: str) -> bytes:
    return base64.b64decode(value, validate=True)


def encode(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def tree_identities(repo: Path, commit: str) -> dict:
    entries = {}
    for raw in git(repo, "ls-tree", "--full-tree", "-r", "-z", "-l", commit).split(b"\0"):
        if not raw:
            continue
        header, path = raw.split(b"\t", 1)
        mode, kind, oid, size = header.decode("ascii").split()
        if not path or path in entries:
            raise ValueError("malformed or duplicate pinned Git path")
        entries[path] = (mode, kind, oid, None if size == "-" else int(size))
    return entries



HELP = re.compile(rb"^[ \t]*(?:help|---help---)[ \t]*\r?$")


def source_context(lines: list[bytes]) -> dict[int, str]:
    """Classify physical source-line *candidates* without dropping lexical rows.

    Kconfig help bodies can contain arbitrary examples resembling directives.
    The old lexical inventory remains immutable; only this supplemental
    per-line evidence labels help/continuation ambiguity. Tab expansion is
    used only for a conservative physical indentation comparison, never to
    claim configuration reachability or run the Kconfig parser.
    """
    result: dict[int, str] = {}
    help_indent: tuple[int, bytes] | None = None
    continued = False
    for number, physical in enumerate(lines, 1):
        line = physical.removesuffix(b"\r")
        stripped = line.lstrip(b" \t")
        prefix = line[:len(line) - len(stripped)]
        column = len(prefix.expandtabs(8))
        if help_indent is not None and stripped.strip() and column <= help_indent[0]:
            help_indent = None
        if SOURCE.match(line) is not None:
            if continued:
                status = "UNRESOLVED_PHYSICAL_CONTINUATION"
            elif help_indent is None:
                status = "DIRECTIVE_LEXICAL_CANDIDATE"
            elif (b" " in prefix and b"\t" in prefix) or (
                    b" " in help_indent[1] and b"\t" in help_indent[1]):
                status = "UNRESOLVED_MIXED_HELP_INDENTATION"
            else:
                status = "HELP_TEXT_LEXICAL_ONLY"
            result[number] = status
        if help_indent is None and HELP.fullmatch(line):
            help_indent = (column, prefix)
        continued = line.endswith(b"\\")
    return result


def literal_target(parent: bytes, kind: str, operand: bytes, paths: dict):
    """Pure byte-path projection; no environmental or filesystem resolution."""
    if not operand or b"\0" in operand:
        return "UNRESOLVED_LITERAL_SYNTAX", None, None
    if operand[:1] == b'"':
        if len(operand) < 3 or operand[-1:] != b'"':
            return "UNRESOLVED_LITERAL_SYNTAX", None, None
        target = operand[1:-1]
    elif operand[:1] == b"'":
        return "UNRESOLVED_LITERAL_SYNTAX", None, None
    else:
        target = operand
    if (not target or any(x in target for x in (b'"', b"'", b"#"))
            or any(x in target for x in (b" ", b"\t", b"\r", b"\n"))):
        return "UNRESOLVED_LITERAL_SYNTAX", None, None
    if any(byte in DYNAMIC for byte in target):
        return "UNRESOLVED_VARIABLE_GLOB_OR_ESCAPE", None, None
    # Kconfig source/osource are relative to srctree; rsource/orsource to
    # directory of the current source. Never follow absolute or parent escapes.
    if target.startswith(b"/"):
        return "OUTSIDE_TRACKED_TREE", None, None
    anchor = posixpath.dirname(parent) if kind in ("rsource", "orsource") else b""
    resolved = posixpath.normpath(posixpath.join(anchor, target))
    if resolved in (b".", b"..") or resolved.startswith(b"../"):
        return "OUTSIDE_TRACKED_TREE", None, None
    hit = paths.get(resolved)
    if hit is None:
        return ("OPTIONAL_UNTRACKED_LITERAL" if kind in ("osource", "orsource")
                else "REQUIRED_UNTRACKED_LITERAL"), resolved, None
    return ("TRACKED_REGULAR_LITERAL" if hit["mode"] in ("100644", "100755")
            and hit["type"] == "blob" else "TRACKED_NONREGULAR_LITERAL"), resolved, hit


def collect(repo: Path, commit: str, source_bytes: bytes, edge_bytes: bytes,
            inventory: dict):
    if not isinstance(commit, str) or not SHA1.fullmatch(commit):
        raise ValueError("full lowercase Linux commit required")
    if git(repo, "rev-parse", "HEAD").strip().decode("ascii") != commit:
        raise ValueError("pinned Linux HEAD mismatch")
    if git(repo, "cat-file", "-t", commit) != b"commit\n":
        raise ValueError("missing pinned Linux commit")
    root = git(repo, "rev-parse", commit + "^{tree}").strip().decode("ascii")
    if (inventory["linux_commit"] != commit or inventory["linux_root_tree"] != root
            or hashlib.sha256(source_bytes).hexdigest() != inventory["source_paths_sha256"]
            or hashlib.sha256(edge_bytes).hexdigest() != inventory["kconfig_source_edges_sha256"]):
        raise ValueError("source/edge ledger is not bound to the pinned tree")
    paths = {}
    for line in source_bytes.splitlines():
        row = json.loads(line)
        path = decode(row["path_b64"])
        if not path or path in paths or not SHA1.fullmatch(row["oid"]):
            raise ValueError("duplicate or malformed source identity")
        paths[path] = row
    if len(paths) != inventory["counts"]["tracked_paths"]:
        raise ValueError("incomplete source path ledger")
    actual = tree_identities(repo, commit)
    declared = {path: (row["mode"], row["type"], row["oid"], row["size"])
                for path, row in paths.items()}
    if declared != actual:
        raise ValueError("source path ledger differs from complete pinned Git tree")

    # Recount the physical lexical sites independently of the edge ledger's
    # count field. Reuse content when multiple tracked paths name one blob.
    records, counts, scope_counts, seen, blob_lines, contexts = [], Counter(), Counter(), set(), {}, {}
    expected = set()
    for path, (mode, _kind, oid, size) in actual.items():
        basename = path.rsplit(b"/", 1)[-1]
        if not (basename == b"Kconfig" or basename.startswith(b"Kconfig.")):
            continue
        if mode not in ("100644", "100755"):
            continue
        if oid not in blob_lines:
            blob = git(repo, "cat-file", "blob", oid)
            if len(blob) != size:
                raise ValueError("Kconfig original Git blob size mismatch")
            blob_lines[oid] = blob.splitlines()
        expected.update((path, number) for number, line in enumerate(blob_lines[oid], 1)
                        if SOURCE.match(line))
    for line in edge_bytes.splitlines():
        edge = json.loads(line)
        path = decode(edge["path_b64"])
        original = paths.get(path)
        if not original or original["oid"] != edge["blob_oid"]:
            raise ValueError("Kconfig include source blob identity mismatch")
        if original["mode"] not in ("100644", "100755"):
            raise ValueError("nonregular Kconfig source")
        number, kind = edge["line"], edge["kind"]
        if type(number) is not int or number < 1 or kind not in (
                "source", "rsource", "osource", "orsource"):
            raise ValueError("invalid Kconfig source edge")
        identity = (path, number)
        if identity in seen:
            raise ValueError("duplicate Kconfig include source line")
        if identity not in expected:
            raise ValueError("Kconfig source line differs from immutable blob")
        seen.add(identity)
        if edge["blob_oid"] not in contexts:
            contexts[edge["blob_oid"]] = source_context(blob_lines[edge["blob_oid"]])
        lines = blob_lines[edge["blob_oid"]]
        if number > len(lines):
            raise ValueError("Kconfig line absent from immutable blob")
        match = SOURCE.match(lines[number - 1])
        if (match is None or match.group(1).decode("ascii") != kind
                or match.group(2) != decode(edge["operand_b64"])):
            raise ValueError("Kconfig source line differs from immutable blob")
        status, target, hit = literal_target(path, kind, match.group(2), paths)
        context = contexts[edge["blob_oid"]][number]
        row = {**edge, "resolution": status, "source_context": context, "target_path_b64": encode(target) if target is not None else None,
               "target_oid": hit["oid"] if hit is not None else None,
               "target_mode": hit["mode"] if hit is not None else None}
        records.append(row)
        counts[status] += 1
        scope_counts[context] += 1
    if seen != expected or len(records) != inventory["counts"]["kconfig_source_edges"]:
        raise ValueError("incomplete Kconfig include edge ledger")
    if git(repo, "rev-parse", "HEAD").strip().decode("ascii") != commit:
        raise ValueError("Linux HEAD moved during include-target audit")
    content = b"".join((json.dumps(x, sort_keys=True, separators=(",", ":")) + "\n").encode("ascii")
                       for x in records)
    report = {"schema": "heptakernel.linux-kconfig-literal-targets.v1",
              "status": "PARTIAL_LITERAL_TARGETS_NOT_ACTIVE_KCONFIG_GRAPH",
              "linux_commit": commit, "linux_root_tree": root,
              "source_file": "kconfig-literal-targets.jsonl",
              "source_sha256": hashlib.sha256(content).hexdigest(),
              "upstream_edges_sha256": hashlib.sha256(edge_bytes).hexdigest(),
              "upstream_paths_sha256": hashlib.sha256(source_bytes).hexdigest(),
              "counts": {**dict(sorted(counts.items())), "all_lexical_edges": len(records)},
              "context_counts": dict(sorted(scope_counts.items())),
              "inventory_complete": False, "full_rewrite_complete": False,
              "limitations": ["All Kconfig conditions and environment substitutions are unevaluated",
                              "Help/continuation classifications are physical-line hints, not parsed Kconfig syntax",
                              "Tracked literal target does not imply an active or reachable include",
                              "Untracked required targets may be conditional or generated",
                              "Symlinks are not followed; globs/variables remain unresolved",
                              "No Linux functionality or HIA compiler capability is implemented"]}
    return content, report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    args = parser.parse_args()
    root = args.inventory
    lock = json.loads(args.lock.read_bytes())
    original = json.loads((root / "report.json").read_bytes())
    content, report = collect(args.repo, lock["linux"]["commit"],
                              (root / "source-paths.jsonl").read_bytes(),
                              (root / "kconfig-source-edges.jsonl").read_bytes(), original)
    (root / report["source_file"]).write_bytes(content)
    (root / "kconfig-literal-targets-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
