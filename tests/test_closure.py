#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Negative controls against shrinking or falsely closing the Linux ledger."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("heptakernel_closure", ROOT / "tools/check_closure.py")
closure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(closure)


def main():
    baseline = json.loads((ROOT / "compatibility/coverage.json").read_text())
    mutations = {
        "changed schema": lambda d: d.update(schema="other"),
        "narrowed target": lambda d: d.update(scope="x86 only"),
        "changed baseline": lambda d: d["baseline"].update(linux_commit="0" * 40),
        "removed gate": lambda d: d["gates"].pop(),
        "duplicated gate": lambda d: d["gates"].append(copy.deepcopy(d["gates"][0])),
        "removed source family": lambda d: d["source_family_obligations"]["arch"].pop(),
        "changed source identity": lambda d: d["source_family_obligations"]["arch"][0].update(
            upstream_tree_sha="0" * 40),
        "removed syscall": lambda d: d["x86_64_syscall_table"].pop(),
        "changed syscall identity": lambda d: d["x86_64_syscall_table"][0].update(number=999999),
        "non-boolean closure flag": lambda d: d.update(full_rewrite_complete="true"),
        "invalid status": lambda d: d["gates"][0].update(status="PASS"),
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
        "false_completion_claims_held": 1,
        "whole_kernel_qualified": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()

