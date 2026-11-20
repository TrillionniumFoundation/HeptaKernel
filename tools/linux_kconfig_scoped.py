#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Byte-bound Kconfig property-owner candidates at one exact pinned Git commit.

This does NOT evaluate Kconfig, resolve source directives, translate
continuations, or prove configuration reachability. Every lexical property
candidate from the preexisting ledger remains present, including help text.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

# CI invokes this source with -I: admit only our adjacent audited tools,
# never a caller-controlled PYTHONPATH or current working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from linux_inventory import enumerate_entries, is_kconfig, git, json_line
from linux_kconfig_relations import extract

DECL = re.compile(rb"^[ \t]*(config|menuconfig)[ \t]+([A-Za-z_][A-Za-z0-9_]*)\b")
HELP = re.compile(rb"^[ \t]*(help|---help---)[ \t]*(?:#.*)?$")
# A new Kconfig statement is not a property of a previous config. Do not
# attribute menu/choice/conditional properties to the last config seen.
SCOPE_BREAK = re.compile(
    rb"^[ \t]*(?:mainmenu|menu|endmenu|choice|endchoice|comment|"
    rb"if|endif|source|rsource|osource|orsource)[ \t]+"
    rb"|^[ \t]*(?:endmenu|endchoice|endif)[ \t]*(?:#.*)?$"
)


def classify_blob(data: bytes) -> list[dict]:
    """Retain all exact physical source candidates; label only clear owners.

    Indentation is compared as raw byte prefixes rather than expanding tabs:
    mixing spaces/tabs in a potential owner relation is marked ambiguous.
    """
    lexical = {row["line"]: row for row in extract(data)}
    results = []
    owner: bytes | None = None
    owner_line: int | None = None
    owner_indent: bytes | None = None
    help_indent: bytes | None = None
    previous_continuation = False
    for line, raw in enumerate(data.split(b"\n"), 1):
        indentation = raw[:len(raw) - len(raw.lstrip(b" \t"))]
        stripped = raw[len(indentation):]
        candidate = lexical.get(line)
        # Kconfig help body must be more deeply indented than the 'help'
        # keyword. It is neither a config declaration nor a property.
        in_help = False
        if help_indent is not None:
            if not stripped or indentation.startswith(help_indent) and len(indentation) > len(help_indent):
                in_help = True
            else:
                help_indent = None
        if in_help:
            status = "HELP_TEXT_LEXICAL_ONLY"
        else:
            declaration = DECL.match(raw)
            if declaration:
                owner = declaration.group(2)
                owner_line = line
                owner_indent = indentation
                status = "DECLARATION_LINE"
            elif HELP.match(raw) and owner is not None:
                help_indent = indentation
                status = "HELP_HEADER"
            elif SCOPE_BREAK.match(raw):
                owner = None
                owner_line = None
                owner_indent = None
                status = "STRUCTURAL_BOUNDARY"
            elif candidate is not None:
                if previous_continuation:
                    status = "UNRESOLVED_CONTINUATION"
                elif owner is None or owner_indent is None:
                    status = "UNBOUND_LEXICAL_CANDIDATE"
                elif not indentation.startswith(owner_indent) or len(indentation) <= len(owner_indent):
                    status = "UNBOUND_LEXICAL_CANDIDATE"
                else:
                    status = "SCOPED_LEXICAL_CANDIDATE"
            else:
                status = "OTHER_LINE"
        if candidate is not None:
            bound = status == "SCOPED_LEXICAL_CANDIDATE"
            results.append({
                **candidate,
                "scope_status": status,
                "owner": owner.decode("ascii") if bound else None,
                "owner_declaration_line": owner_line if bound else None,
            })
        if not in_help:
            previous_continuation = stripped.rstrip().endswith(b"\\")
        else:
            previous_continuation = False
    if len(results) != len(lexical):
        raise ValueError("loss of Kconfig lexical relation candidate")
    return results


def collect(repo: Path, commit: str) -> tuple[bytes, dict]:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("exact 40-digit lowercase Linux commit required")
    if git(repo, "rev-parse", "HEAD").strip() != commit.encode("ascii"):
        raise ValueError("pinned Linux HEAD mismatch")
    if git(repo, "cat-file", "-t", commit) != b"commit\n":
        raise ValueError("pinned Linux lock is not a commit")
    root_tree = git(repo, "rev-parse", commit + "^{tree}").strip().decode("ascii")
    records: list[dict] = []
    counts: Counter[str] = Counter()
    for path, entry in enumerate_entries(repo, commit):
        if not is_kconfig(path):
            continue
        counts["kconfig_paths"] += 1
        if entry["type"] != "blob" or entry["mode"] not in ("100644", "100755"):
            counts["unreadable_kconfig_paths"] += 1
            continue
        blob = git(repo, "cat-file", "blob", entry["oid"])
        if len(blob) != entry["size"]:
            raise ValueError("immutable Git Kconfig blob size mismatch")
        counts["scanned_kconfig_paths"] += 1
        binding = {
            "path_b64": base64.b64encode(path).decode("ascii"),
            "blob_oid": entry["oid"],
        }
        for annotated in classify_blob(blob):
            counts[annotated["scope_status"]] += 1
            records.append({**binding, **annotated})
    if not records:
        raise ValueError("empty Kconfig property inventory")
    if git(repo, "rev-parse", "HEAD").strip() != commit.encode("ascii"):
        raise ValueError("Linux HEAD changed during inventory")
    payload = b"".join(json_line(row) for row in records)
    counts["property_candidates"] = len(records)
    report = {
        "schema": "heptakernel.linux-kconfig-property-scope.v1",
        "status": "PARTIAL_LEXICAL_OWNER_CANDIDATES_NOT_KCONFIG_GRAPH",
        "linux_commit": commit,
        "linux_root_tree": root_tree,
        "source_file": "kconfig-property-scopes.jsonl",
        "source_sha256": hashlib.sha256(payload).hexdigest(),
        "counts": dict(sorted(counts.items())),
        "inventory_complete": False,
        "full_rewrite_complete": False,
        "limitations": [
            "Owner is only an indentation-based candidate, not Kconfig semantics",
            "No include expansion, variable substitution, conditional evaluation, or reachability",
            "Continuation and mixed-indentation semantics are not proven",
            "No Linux architecture, driver, ABI or syscall implementation is claimed",
        ],
    }
    return payload, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    lock = json.loads(args.lock.read_bytes())
    payload, report = collect(args.repo, lock["linux"]["commit"])
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / report["source_file"]).write_bytes(payload)
    (args.out / "kconfig-property-scopes-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
