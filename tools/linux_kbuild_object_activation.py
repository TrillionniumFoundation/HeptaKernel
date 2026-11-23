#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fail-closed, source-bound partial Kbuild obj-* activation for a named profile.

This is NOT GNU make, Kbuild graph closure, or Linux driver implementation.
An ACTIVE_LEXICAL_LITERAL means an assignment line has a supported active
condition, NOT that its object survives later assignments or is linked.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess

SHA = re.compile(r"[0-9a-f]{40}\Z")
NAME = re.compile(rb"CONFIG_[A-Z0-9_]+\Z")
OBJ = re.compile(rb"obj-(y|m|n|\$\((CONFIG_[A-Z0-9_]+)\))\Z")
ASSIGN = re.compile(rb"^[ \t]*([^ \t\r\n:=]+)[ \t]*([:+?]?=)[ \t]*(.*?)[ \t\r\n]*\Z", re.S)
SIMPLE_IF = re.compile(rb"^(ifeq|ifneq)[ \t]*\([ \t]*\$\((CONFIG_[A-Z0-9_]+)\)[ \t]*,[ \t]*(y|m|n)[ \t]*\)[ \t]*$")
CONTROL_START = re.compile(rb"^(ifeq|ifneq|ifdef|ifndef)(?=[ \t(]|$)")
CONTROL_ELSE = re.compile(rb"^else(?=[ \t]|$)")
CONTROL_END = re.compile(rb"^endif(?=[ \t]|$)")
INCLUDE = re.compile(rb"^(?:-?include|sinclude)(?=[ \t]|$)")
LITERAL = re.compile(rb"(?:[A-Za-z0-9_+.-]+/)*[A-Za-z0-9_+.-]+\.o\Z")
DIRECTORY = re.compile(rb"(?:[A-Za-z0-9_+.-]+/)+\Z")
MAX_BLOB = 32 * 1024 * 1024


def git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def record_bytes(row: dict) -> bytes:
    return (json.dumps(row, ensure_ascii=True, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("ascii")


def all_kbuild_blobs(repo: Path, commit: str):
    raw = git(repo, "ls-tree", "--full-tree", "-r", "-z", "-l", commit)
    result = []
    seen = set()
    for field in raw.split(b"\0"):
        if not field:
            continue
        meta, sep, path = field.partition(b"\t")
        if sep != b"\t" or not path or path in seen:
            raise ValueError("invalid or repeated immutable tree path")
        seen.add(path)
        name = path.rsplit(b"/", 1)[-1]
        if name not in (b"Makefile", b"Kbuild") and not name.startswith((b"Makefile.", b"Kbuild.")):
            continue
        mode, typ, oid, size = meta.split()
        if not SHA.fullmatch(oid.decode("ascii")):
            raise ValueError("bad object id")
        if (typ, mode) not in ((b"blob", b"100644"), (b"blob", b"100755")):
            result.append((path, None, oid))
            continue
        blob = git(repo, "cat-file", "blob", oid.decode("ascii"))
        if not size.isdigit() or len(blob) != int(size) or len(blob) > MAX_BLOB:
            raise ValueError("immutable Kbuild blob exceeds bound or length differs")
        result.append((path, blob, oid))
    return sorted(result)


def logical_lines(blob: bytes):
    # Only LF (plus optional CR) terminates a physical Makefile line.
    parts = blob.split(b"\n")
    pieces = [part + b"\n" for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])
    cursor = 0
    n = 0
    while n < len(pieces):
        first, start = n + 1, cursor
        raw = pieces[n]
        cursor += len(raw)
        n += 1
        while raw.endswith((b"\\\n", b"\\\r\n")) and n < len(pieces):
            raw += pieces[n]
            cursor += len(pieces[n])
            n += 1
        flat = re.sub(rb"\\\r?\n[ \t]*", b" ", raw)
        yield start, cursor, first, n, raw, flat.strip()
    if cursor != len(blob):
        raise ValueError("failed to traverse entire Kbuild blob")


def tri_and(lhs: bool | None, rhs: bool | None) -> bool | None:
    return False if lhs is False or rhs is False else None if lhs is None or rhs is None else True


def tri_not(value: bool | None) -> bool | None:
    return None if value is None else not value


def tri_or(lhs: bool | None, rhs: bool | None) -> bool | None:
    return True if lhs is True or rhs is True else None if lhs is None or rhs is None else False


def analyze(blob: bytes, path: bytes, oid: bytes, profile: dict[bytes, bytes]):
    # Each frame holds (enclosing activity, whether any arm may have matched,
    # whether the final, unconditional else arm has appeared). Make's else-if
    # chain is a *single* nesting level, not a nested if with another endif.
    stack: list[tuple[bool | None, bool | None, bool]] = []
    active: bool | None = True
    macro_depth = 0
    structural_fault = False
    counts = Counter()
    rows = []
    for start, end, first, last, raw, text in logical_lines(blob):
        counts["logical_statements"] += 1
        if not text or text.startswith(b"#"):
            continue
        if raw.startswith(b"\t"):
            counts["recipe_or_tabbed_lines"] += 1
            continue
        # Make define/endef bodies must not be mistaken for executed assignments.
        if re.match(rb"^define(?:[ \t]|$)", text):
            macro_depth += 1
            counts["deferred_define_blocks"] += 1
            continue
        if text == b"endef" and macro_depth:
            macro_depth -= 1
            continue
        if macro_depth:
            counts["deferred_define_lines"] += 1
            continue
        if CONTROL_START.match(text):
            condition = SIMPLE_IF.fullmatch(text)
            if condition:
                value = profile.get(condition[2])
                local = None if value is None else (value == condition[3])
                if condition[1] == b"ifneq":
                    local = tri_not(local)
            else:
                local = None
                counts["unsupported_conditional_syntax"] += 1
            stack.append((active, local, False))
            active = tri_and(active, local)
            counts["conditional_blocks"] += 1
            continue
        if CONTROL_ELSE.match(text):
            if not stack:
                counts["unmatched_else"] += 1
                structural_fault = True
                active = None
            else:
                parent, taken, had_else = stack[-1]
                clause = text[len(b"else"):].strip()
                if had_else:
                    counts["duplicate_or_post_else_clause"] += 1
                    structural_fault = True
                    active = None
                elif not clause:
                    # Only the fraction not matched by an earlier arm reaches
                    # a bare else. A fully unknown prior arm stays unknown.
                    active = tri_and(parent, tri_not(taken))
                    stack[-1] = (parent, True, True)
                    counts["unconditional_else_arms"] += 1
                elif CONTROL_START.match(clause):
                    condition = SIMPLE_IF.fullmatch(clause)
                    if condition:
                        value = profile.get(condition[2])
                        local = None if value is None else value == condition[3]
                        if condition[1] == b"ifneq":
                            local = tri_not(local)
                    else:
                        local = None
                        counts["unsupported_elseif_syntax"] += 1
                    active = tri_and(parent, tri_and(tri_not(taken), local))
                    stack[-1] = (parent, tri_or(taken, local), False)
                    counts["elseif_arms"] += 1
                else:
                    counts["malformed_else_clause"] += 1
                    structural_fault = True
                    active = None
            continue
        if CONTROL_END.match(text):
            if text != b"endif" or not stack:
                counts["unmatched_or_nonliteral_endif"] += 1
                structural_fault = True
                active = None
            else:
                parent, _, _ = stack.pop()
                active = parent
            continue
        if INCLUDE.match(text):
            counts["unevaluated_include_directives"] += 1
            continue
        m = ASSIGN.fullmatch(text)
        if m is None:
            counts["unresolved_make_statements"] += 1
            continue
        match = OBJ.fullmatch(m[1])
        if match is None:
            counts["other_assignments"] += 1
            continue
        selector = match[1]
        config = match[2]
        chosen = profile.get(config) if config else selector
        selector_known = chosen is not None
        chosen = chosen if chosen in (b"y", b"m", b"n") else None
        if config and not selector_known:
            counts["profile_values_not_specified"] += 1
        rhs = m[3]
        raw_tokens = rhs.split()
        if not raw_tokens:
            raw_tokens = [b""]
        for token in raw_tokens:
            is_literal = bool((LITERAL.fullmatch(token) or DIRECTORY.fullmatch(token))
                              and all(part not in (b".", b"..") for part in token.split(b"/")))
            if not is_literal:
                status = "UNRESOLVED_OBJECT_EXPRESSION"
            elif active is None or chosen is None:
                status = "UNRESOLVED_SCOPE_OR_CONFIG"
            elif active is False or chosen == b"n":
                status = "INACTIVE_LEXICAL_LITERAL"
            elif chosen in (b"y", b"m"):
                status = "ACTIVE_LEXICAL_LITERAL"
            else:
                raise AssertionError("selector classification unreachable")
            # An active lexical line is not guaranteed to survive later Make
            # reassignments, includes, variable expansion, or recursive builds.
            row = {
                "path_b64": b64(path), "blob_oid": oid.decode("ascii"),
                "start_byte": start, "end_byte": end,
                "start_line": first, "end_line": last,
                "raw_sha256": hashlib.sha256(raw).hexdigest(),
                "lhs_b64": b64(m[1]), "operator": m[2].decode("ascii"),
                "token_b64": b64(token),
                "config_b64": b64(config) if config else None,
                "profile_value": chosen.decode("ascii") if chosen is not None else None,
                "conditional_state": "unknown" if active is None else "true" if active else "false",
                "status": status,
            }
            rows.append(row)
            counts[status] += 1
    if stack or macro_depth or structural_fault:
        counts["unclosed_constructs"] += len(stack) + macro_depth + int(structural_fault)
        # Future additions must not silently claim successful scope analysis.
        for row in rows:
            if row["status"] == "ACTIVE_LEXICAL_LITERAL":
                row["status"] = "UNRESOLVED_SCOPE_OR_CONFIG"
                counts["ACTIVE_LEXICAL_LITERAL"] -= 1
                counts["UNRESOLVED_SCOPE_OR_CONFIG"] += 1
    return rows, counts


def parse_profile(data: bytes) -> dict[bytes, bytes]:
    if len(data) > 128 * 1024:
        raise ValueError("explicit profile exceeds input bound")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate explicit profile key")
            result[key] = value
        return result
    value = json.loads(data, object_pairs_hook=unique)
    if type(value) is not dict or set(value) != {"schema", "values"} or value["schema"] != "heptakernel.kbuild-explicit-profile.v1" or type(value["values"]) is not dict:
        raise ValueError("explicit profile schema mismatch")
    if len(value["values"]) > 10000:
        raise ValueError("too many explicit profile variables")
    result = {}
    for k, v in value["values"].items():
        if type(k) is not str or not k.isascii() or not NAME.fullmatch(k.encode("ascii")) or type(v) is not str or v not in ("y", "m", "n"):
            raise ValueError("profile must be exact CONFIG_X tristates only")
        result[k.encode("ascii")] = v.encode("ascii")
    return result


def build(repo: Path, lock: Path, explicit_profile: Path, out: Path) -> dict:
    commit = json.loads(lock.read_bytes())["linux"]["commit"]
    if type(commit) is not str or not SHA.fullmatch(commit):
        raise ValueError("pinned Linux SHA is malformed")
    if git(repo, "rev-parse", "HEAD").strip() != commit.encode("ascii") or git(repo, "cat-file", "-t", commit) != b"commit\n":
        raise ValueError("pinned Linux HEAD mismatch")
    profile_bytes = explicit_profile.read_bytes()
    profile = parse_profile(profile_bytes)
    rows, counts = bytearray(), Counter()
    for path, blob, oid in all_kbuild_blobs(repo, commit):
        counts["all_kbuild_paths"] += 1
        if blob is None:
            counts["nonregular_paths"] += 1
            continue
        counts["regular_kbuild_paths"] += 1
        current, measured = analyze(blob, path, oid, profile)
        for key, amount in measured.items():
            counts[key] += amount
        for row in current:
            rows.extend(record_bytes(row))
    if git(repo, "rev-parse", "HEAD").strip() != commit.encode("ascii"):
        raise ValueError("source changed during pinned scan")
    payload = bytes(rows)
    report = {
        "schema": "heptakernel.kbuild-partial-object-activation.v1",
        "linux_commit": commit,
        "linux_tree": git(repo, "rev-parse", commit + "^{tree}").strip().decode("ascii"),
        "profile_sha256": hashlib.sha256(profile_bytes).hexdigest(),
        "records_sha256": hashlib.sha256(payload).hexdigest(),
        "counts": dict(sorted(counts.items())),
        "status": "PARTIAL_LEXICAL_KBUILD_NOT_LINK_GRAPH",
        "active_objects_proven_linked": False,
        "conditional_and_variable_expansion_complete": False,
        "full_linux_rewrite_complete": False,
        "full_linux_acceptance": "HOLD",
        "limitations": [
            "ACTIVE_LEXICAL_LITERAL denotes supported assignment-line activation only, not final variable value or linked object.",
            "Supported else ifeq/ifneq arms use three-valued first-match semantics; unknown earlier arms never authorize later arms.",
            "Unknown CONFIG, unsupported conditionals, includes, definitions, recursive Make and dynamic RHS remain unresolved.",
            "The 17 full-system gates and 422 syscall rows are not credited or narrowed.",
        ],
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "kbuild-object-candidates.jsonl").write_bytes(payload)
    (out / "report.json").write_bytes(json.dumps(report, sort_keys=True, indent=2).encode("ascii") + b"\n")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--lock", type=Path, required=True)
    p.add_argument("--profile", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(build(a.repo, a.lock, a.profile, a.out), sort_keys=True))


if __name__ == "__main__":
    main()
