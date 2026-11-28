#!/usr/bin/env python3
"""Read exact hosted native page-suite ZIP bytes without extracting or executing them."""

import argparse
import collections
import hashlib
import json
import re
import stat
import zipfile

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
ARTIFACT_LIMIT = 128 * 1024 * 1024
PAYLOAD_LIMIT = 512 * 1024 * 1024
ENTRY_LIMIT = 20_000
REPORT_LIMIT = 4 * 1024 * 1024
MACHINES = {"pc", "q35"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def hash_stream(reader):
    digest = hashlib.sha256()
    for chunk in iter(lambda: reader.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def file_digest(z, member):
    with z.open(member) as reader:
        return hash_stream(reader)


def unique_json(pairs):
    out = {}
    for key, value in pairs:
        require(key not in out, f"duplicate JSON key: {key}")
        out[key] = value
    return out


def read_artifact(path, zip_sha256, suite, report_sha256, per_machine):
    require(bool(PART.fullmatch(suite)), "invalid suite name")
    require(bool(SHA256.fullmatch(zip_sha256) and SHA256.fullmatch(report_sha256)),
            "both SHA-256 pins must be lowercase hexadecimal")
    require(per_machine > 0, "expected cases per machine must be positive")
    with open(path, "rb") as original:
        original.seek(0, 2)
        size = original.tell()
        require(0 < size <= ARTIFACT_LIMIT, "archive size outside reader limit")
        original.seek(0)
        require(hash_stream(original) == zip_sha256, "archive SHA-256 mismatch")
        original.seek(0)
        with zipfile.ZipFile(original) as z:
            entries = z.infolist()
            require(0 < len(entries) <= ENTRY_LIMIT, "archive entry count outside reader limit")
            require(sum(i.file_size for i in entries) <= PAYLOAD_LIMIT,
                    "total uncompressed size exceeds reader limit")
            inventory = {}
            for i in entries:
                mode = stat.S_IFMT(i.external_attr >> 16)
                require(not i.is_dir() and mode in {0, stat.S_IFREG}
                        and all(PART.fullmatch(p) for p in i.filename.split("/"))
                        and not i.flag_bits & 1
                        and i.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED},
                        f"unsupported archive entry: {i.filename!r}")
                require(i.filename not in inventory, f"duplicate archive entry: {i.filename!r}")
                inventory[i.filename] = i
            bad = z.testzip()
            require(bad is None, f"CRC failure: {bad!r}")
            report_path = f"{suite}/report.json"
            report_info = inventory.get(report_path)
            require(report_info is not None and 0 < report_info.file_size <= REPORT_LIMIT,
                    "missing or oversized suite report")
            report_bytes = z.read(report_info)
            require(hashlib.sha256(report_bytes).hexdigest() == report_sha256, "report SHA-256 mismatch")
            report = json.loads(report_bytes, object_pairs_hook=unique_json)
            require(isinstance(report, dict) and report.get("status") == "PASS",
                    "suite report is not PASS")
            require(report.get("full_linux_acceptance") == "HOLD",
                    "suite report must preserve its explicit full Linux HOLD")
            cases = report.get("cases")
            require(isinstance(cases, list) and len(cases) == 2 * per_machine,
                    "wrong total case count")
            seen, counts, hashes = set(), collections.Counter(), {}
            for row in cases:
                require(isinstance(row, dict), "invalid case record")
                machine, name = row.get("machine"), row.get("case")
                require(isinstance(machine, str) and machine in MACHINES
                        and isinstance(name, str) and PART.fullmatch(name), "invalid case identity")
                require((machine, name) not in seen, f"duplicate case: {machine}/{name}")
                seen.add((machine, name))
                counts[machine] += 1
                require(row.get("status") == "PASS" and type(row.get("expected_rc")) is int
                        and type(row.get("returncode")) is int and row["returncode"] == row["expected_rc"]
                        and isinstance(row.get("expected_serial"), str) and row["expected_serial"]
                        and row.get("serial") == row["expected_serial"],
                        f"case result mismatch: {machine}/{name}")
                for filename, key in (("guest.elf", "guest_sha256"), ("guest32.elf", "image_sha256")):
                    member = f"{suite}/{name}/{filename}"
                    require(member in inventory, f"missing image: {member}")
                    if member not in hashes:
                        hashes[member] = file_digest(z, inventory[member])
                    require(hashes[member] == row.get(key), f"image SHA-256 mismatch: {member}")
            require(counts == {key: per_machine for key in MACHINES}
                    and all((other, name) in seen for _, name in seen for other in MACHINES),
                    "PC and Q35 must contain the same complete case identities")
    return {"status": "PASS", "suite": suite, "archive_bytes": size,
            "archive_sha256": zip_sha256, "archive_entries_crc_checked": len(entries),
            "report_sha256": report_sha256, "cases_by_machine": dict(sorted(counts.items())),
            "unique_images_verified": len(hashes), "full_linux_acceptance": "HOLD"}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("zip_path")
    ap.add_argument("--zip-sha256", required=True)
    ap.add_argument("--suite", required=True)
    ap.add_argument("--report-sha256", required=True)
    ap.add_argument("--cases-per-machine", required=True, type=int)
    args = ap.parse_args()
    try:
        result = read_artifact(args.zip_path, args.zip_sha256, args.suite,
                               args.report_sha256, args.cases_per_machine)
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile, NotImplementedError) as exc:
        ap.exit(1, f"artifact rejected: {exc}\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
