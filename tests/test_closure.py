#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Negative controls against shrinking or falsely closing the Linux ledger."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("heptakernel_closure", ROOT / "tools/check_closure.py")
closure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(closure)


def check_evidence_pins():
    with TemporaryDirectory() as work:
        root = Path(work)
        # Force a multi-chunk hash and keep the implementation distinct from
        # both the behavior receipt and the upstream errno evidence.
        payload = b"fixture-only\n" * 100_000
        (root / "receipt.json").write_bytes(payload)
        (root / "upstream.json").write_bytes(b"upstream fixture\n")
        (root / "native.hepta").write_text("fixture\n")
        (root / "empty.json").touch()
        receipt = {"path": "receipt.json", "sha256": hashlib.sha256(payload).hexdigest()}
        upstream = {
            "path": "upstream.json",
            "sha256": hashlib.sha256(b"upstream fixture\n").hexdigest(),
        }
        wrong = dict(receipt, sha256="0" * 64)
        absent = dict(receipt, path="absent.json")
        empty = {"path": "empty.json", "sha256": hashlib.sha256(b"").hexdigest()}
        checks = 0
        for kind in ("gate", "source", "syscall"):
            row = {
                "status": "VERIFIED_SCOPE",
                "entry": "sys_example",
                "implementation_paths": ["native.hepta"],
                "evidence": [receipt],
            }
            assert closure.row_ready(root, row, kind=kind)
            checks += 1
            for evidence in (["receipt.json"], [wrong], [absent], [empty],
                             [receipt, "upstream.json"], []):
                assert not closure.row_ready(root, dict(row, evidence=evidence), kind=kind)
                checks += 1
        row = {
            "status": "NOT_APPLICABLE_WITH_EVIDENCE",
            "entry": None,
            "baseline_behavior":
                "UPSTREAM_UNIMPLEMENTED_OR_OBSOLETE_REQUIRES_MATCHING_ERRNO",
            "implementation_paths": [],
            "evidence": [receipt],
            "baseline_evidence": [upstream],
        }
        assert closure.row_ready(root, row, kind="syscall")
        assert not closure.row_ready(root, dict(row, baseline_evidence=["upstream.json"]), kind="syscall")
        assert not closure.row_ready(root, dict(row, evidence=["receipt.json"]), kind="syscall")
        assert not closure.row_ready(root, row, kind="gate")
        (root / "receipt.json").write_bytes(payload + b"changed")
        assert not closure.row_ready(root, row, kind="syscall")
        return checks + 5


def check_duplicate_cli(baseline):
    # The surviving value would be valid if the parser only kept the last
    # occurrence; test nested duplicates as well as a top-level duplicate.
    plain = json.dumps(baseline, separators=(",", ":"))
    documents = [
        '{"schema":"wrong",' + plain[1:],
        plain.replace('"linux_version":', '"linux_version":"wrong","linux_version":', 1),
    ]
    with TemporaryDirectory() as work:
        manifest = Path(work) / "coverage.json"
        for text in documents:
            manifest.write_text(text, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools/check_closure.py"), "--manifest", str(manifest)],
                capture_output=True, text=True, check=False,
            )
            output = json.loads(result.stdout)
            assert result.returncode == 1 and output["status"] == "INVALID_MANIFEST", output
            assert "duplicate JSON object member" in output["error"], output
    return len(documents)


def main():
    baseline = json.loads((ROOT / "compatibility/coverage.json").read_text())
    mutations = {
        "changed schema": lambda d: d.update(schema="other"),
        "narrowed target": lambda d: d.update(scope="x86 only"),
        "changed baseline": lambda d: d["baseline"].update(linux_commit="0" * 40),
        "changed Hepta baseline": lambda d: d["baseline"].update(hepta_commit="0" * 40),
        "removed gate": lambda d: d["gates"].pop(),
        "duplicated gate": lambda d: d["gates"].append(copy.deepcopy(d["gates"][0])),
        "removed source family": lambda d: d["source_family_obligations"]["arch"].pop(),
        "changed source identity": lambda d: d["source_family_obligations"]["arch"][0].update(
            upstream_tree_sha="0" * 40),
        "removed syscall": lambda d: d["x86_64_syscall_table"].pop(),
        "changed syscall identity": lambda d: d["x86_64_syscall_table"][0].update(number=999999),
        "non-boolean closure flag": lambda d: d.update(full_rewrite_complete="true"),
        "invalid status": lambda d: d["gates"][0].update(status="PASS"),
        "non-string status": lambda d: d["gates"][0].update(status=[]),
        "external evidence path": lambda d: d["gates"][0].update(evidence=["../external.json"]),
    }
    for name, mutate in mutations.items():
        data = copy.deepcopy(baseline)
        mutate(data)
        try:
            closure.inspect(data, ROOT)
        except closure.ManifestError:
            pass
        else:
            raise AssertionError("invalid manifest accepted: " + name)
    false_claim = copy.deepcopy(baseline)
    false_claim.update(inventory_complete=True, full_rewrite_complete=True)
    for gate in false_claim["gates"]:
        gate.update(status="NOT_IMPLEMENTED", evidence=[])
    assert closure.inspect(false_claim, ROOT)["status"] == "HOLD"
    print(json.dumps({
        "schema": "heptakernel.closure-negative-controls.v1",
        "status": "PASS",
        "malformed_manifests_rejected": len(mutations),
        "duplicate_json_inputs_rejected": check_duplicate_cli(baseline),
        "evidence_pin_checks": check_evidence_pins(),
        "false_completion_claims_held": 1,
        "whole_kernel_qualified": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()

