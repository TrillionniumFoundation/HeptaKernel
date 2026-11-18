#!/usr/bin/env python3
"""Independent provenance and cross-report isolation check for native HIA PTE downgrades.

A green RW->RO report previously overwrote the RX->NX report path (and vice
versa).  The old artifact therefore could not demonstrate that both native
oracles actually ran.  This verifier binds each report to its own HIA source,
native shared object and specific differential campaign. It never claims
hardware TLB, privileged backend or SMP verification from the host tests.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path


SCHEMA = "heptakernel.pt-native-downgrade.v1"
CASES = 4016
CONFIG = {
    "RX_TO_NX": (
        Path("build/x86-pt-nx-protect-report.json"),
        Path("src/x86_pt_nx_protect.hepta"),
        Path("build/x86-pt-nx-protect.so"),
    ),
    "RW_TO_RO": (
        Path("build/x86-pt-write-protect-report.json"),
        Path("src/x86_pt_write_protect.hepta"),
        Path("build/x86-pt-write-protect.so"),
    ),
}


class ReportRejected(ValueError):
    pass


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ReportRejected(reason)


def check_report(report: dict, operation: str, source_hash: str, library_hash: str) -> None:
    require(isinstance(report, dict), "report is not a JSON object")
    require(operation in CONFIG, "unrecognized native operation")
    require(report.get("schema") == SCHEMA, "wrong report schema")
    require(report.get("operation") == operation, "wrong operation or crossed reports")
    require(report.get("status") == "PASS", "not a passing native oracle")
    require(report.get("source_sha256") == source_hash, "HIA source identity mismatch")
    require(report.get("library_sha256") == library_hash, "native library identity mismatch")
    for field in ("cases", "allowed", "refused"):
        value = report.get(field)
        require(type(value) is int and value >= 0, "invalid native count: " + field)
    require(report["cases"] == CASES, "unexpected campaign cardinality")
    require(report["allowed"] >= 600, "insufficient positive native cases")
    require(report["refused"] >= 2000, "insufficient refused native cases")
    require(report["allowed"] + report["refused"] == CASES, "inconsistent native counts")
    require(report.get("hardware_tlb_verified") is False,
            "host differential campaign cannot claim hardware TLB")
    require(report.get("smp_atomicity_verified") is False,
            "host differential campaign cannot claim SMP atomicity")


def adversarial_controls(report: dict, operation: str, source_hash: str, library_hash: str) -> int:
    """Exercise the verifier on corrupt / forged reports, independently of HIA."""
    controls = (
        {"operation": "RW_TO_RO" if operation == "RX_TO_NX" else "RX_TO_NX"},
        {"schema": "legacy"},
        {"status": "PASS", "source_sha256": "0" * 64},
        {"library_sha256": "f" * 64},
        {"cases": CASES - 1},
        {"allowed": 0, "refused": CASES},
        {"cases": 0, "allowed": 0, "refused": 0},
        {"hardware_tlb_verified": True},
        {"smp_atomicity_verified": True},
    )
    count = 0
    for corruption in controls:
        mutant = copy.deepcopy(report)
        mutant.update(corruption)
        try:
            check_report(mutant, operation, source_hash, library_hash)
        except ReportRejected:
            count += 1
        else:
            raise ReportRejected("malicious report accepted: " + str(corruption))
    return count


def main() -> None:
    report_paths = [row[0].resolve() for row in CONFIG.values()]
    require(len(set(report_paths)) == len(report_paths), "report paths alias")
    data = {}
    controls = 0
    for operation, (report_path, source_path, library_path) in CONFIG.items():
        require(report_path.is_file(), "missing report: " + str(report_path))
        require(source_path.is_file(), "missing HIA source: " + str(source_path))
        require(library_path.is_file(), "missing native library: " + str(library_path))
        report = json.loads(report_path.read_text())
        source_hash = digest(source_path)
        library_hash = digest(library_path)
        check_report(report, operation, source_hash, library_hash)
        controls += adversarial_controls(report, operation, source_hash, library_hash)
        data[operation] = {
            "report_sha256": digest(report_path),
            "source_sha256": source_hash,
            "library_sha256": library_hash,
            "cases": report["cases"],
            "allowed": report["allowed"],
            "refused": report["refused"],
        }
    require(data["RX_TO_NX"]["library_sha256"] != data["RW_TO_RO"]["library_sha256"],
            "two native operations unexpectedly have identical shared-object identity")
    result = {
        "schema": "heptakernel.pt-downgrade-isolation.v1",
        "status": "PASS",
        "negative_controls_rejected": controls,
        "operations": data,
        "full_linux_acceptance": "HOLD",
        "native_privilege_backend_verified": False,
        "hardware_tlb_verified_by_these_reports": False,
        "smp_atomicity_verified": False,
    }
    target = Path("build/pt-downgrade-report-isolation.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("independent native HIA PTE downgrade reports:", json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
