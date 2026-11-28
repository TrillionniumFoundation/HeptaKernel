"""Independent CLI fixtures for the native page archive reader."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile

TOOL = Path(__file__).resolve().parents[1] / "tools/read_native_page_ci.py"


def sha(data):
    return hashlib.sha256(data).hexdigest()


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.archive = Path(tmp.name) / "test.zip"
        self.elf, self.elf32 = b"guest evidence one", b"guest evidence two"
        self.rows = [
            {"case": "case-one", "machine": machine, "expected_rc": 33, "returncode": 33,
             "expected_serial": "P", "serial": "P", "status": "PASS",
             "guest_sha256": sha(self.elf), "image_sha256": sha(self.elf32)}
            for machine in ("pc", "q35")
        ]
        self.report = {"status": "PASS", "full_linux_acceptance": "HOLD", "cases": self.rows}

    def build(self, *, image=None, duplicate=False, unsafe=False, report=None, omit=False):
        raw = json.dumps(self.report).encode() if report is None else report
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.archive, "w") as z:
                z.writestr("suite/report.json", raw)
                z.writestr("suite/case-one/guest.elf", self.elf if image is None else image)
                if not omit:
                    z.writestr("suite/case-one/guest32.elf", self.elf32)
                if duplicate:
                    z.writestr("suite/report.json", raw)
                if unsafe:
                    z.writestr("suite/../other", b"not extracted")
        self.report_digest = sha(raw)
        self.archive_digest = sha(self.archive.read_bytes())

    def call(self, zip_pin=None, report_pin=None, count="1"):
        return subprocess.run(
            [sys.executable, "-I", "-B", str(TOOL), str(self.archive), "--suite", "suite",
             "--zip-sha256", zip_pin or self.archive_digest,
             "--report-sha256", report_pin or self.report_digest, "--cases-per-machine", count],
            text=True, capture_output=True, check=False, timeout=10)

    def reject(self, expected, **kw):
        result = self.call(**kw)
        self.assertEqual(result.returncode, 1, result)
        self.assertIn(expected, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_valid_reports_both_archives_and_case_custody(self):
        self.build()
        result = self.call()
        self.assertEqual(result.returncode, 0, result)
        data = json.loads(result.stdout)
        self.assertEqual(data["cases_by_machine"], {"pc": 1, "q35": 1})
        self.assertEqual(data["unique_images_verified"], 2)
        self.assertEqual(data["archive_entries_crc_checked"], 3)
        self.assertEqual(data["full_linux_acceptance"], "HOLD")

    def test_archive_digest(self):
        self.build()
        self.reject("archive SHA-256 mismatch", zip_pin="0" * 64)

    def test_report_digest(self):
        self.build()
        self.reject("report SHA-256 mismatch", report_pin="0" * 64)

    def test_case_count(self):
        self.build()
        self.reject("wrong total case count", count="2")

    def test_misreported_exit(self):
        self.rows[0]["returncode"] = 35
        self.build()
        self.reject("case result mismatch")

    def test_duplicate_case(self):
        self.rows[1]["machine"] = "pc"
        self.build()
        self.reject("duplicate case")

    def test_guest_bytes_do_not_match_report(self):
        self.build(image=b"other ELF")
        self.reject("image SHA-256 mismatch")

    def test_missing_guest(self):
        self.build(omit=True)
        self.reject("missing image")

    def test_duplicate_zip_entry(self):
        self.build(duplicate=True)
        self.reject("duplicate archive entry")

    def test_unsupported_archive_entry(self):
        self.build(unsafe=True)
        self.reject("unsupported archive entry")

    def test_duplicate_json_key(self):
        self.build(report=b'{"status":"PASS","status":"PASS"}')
        self.reject("duplicate JSON key")

    def test_crc_failure_even_with_matching_archive_pin(self):
        self.build()
        raw = self.archive.read_bytes()
        self.assertEqual(raw.count(self.elf), 1)
        changed = raw.replace(self.elf, b"x" + self.elf[1:])
        self.archive.write_bytes(changed)
        self.reject("CRC failure", zip_pin=sha(changed))

    def test_hold_cannot_be_promoted(self):
        self.report["full_linux_acceptance"] = "PASS"
        self.build()
        self.reject("explicit full Linux HOLD")


if __name__ == "__main__":
    unittest.main()
