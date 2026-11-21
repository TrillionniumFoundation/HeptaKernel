#!/usr/bin/env python3
"""QEMU byte-level independent observer: two HIA-PMM-owned shadow table frames.

Exactly the pinned native HIA PMM, offline shadow builder and PMM-frame
admission source objects are linked into each guest. The bridge, not HIA,
executes CR3 reload and the one parent PDE store. Full Linux remains HOLD.
"""
import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

CASES = {
    "hw": ("HEPTAKERNEL HIA LIVE PMM SHADOW FRAME CPU PUBLISH VERIFIED", 33),
    "stale": ("HEPTAKERNEL HIA LIVE SHADOW STALE PARENT REFUSED UNCHANGED", 35),
    "liar": ("HEPTAKERNEL HIA LIVE SHADOW DISHONEST ADMIT DETECTED", 35),
    "bitmap": ("HEPTAKERNEL HIA LIVE SHADOW MISSING PMM CLAIM REFUSED", 35),
    "recheck": ("HEPTAKERNEL HIA LIVE SHADOW POSTADMIT PMM CHANGE REFUSED", 35),
    "free-stale": ("HEPTAKERNEL HIA SHADOW COMPLETE PMM FREE COUNT STALE REFUSED", 35),
    "free-liar": ("HEPTAKERNEL HIA SHADOW DISHONEST FULL PMM CHECK DETECTED", 35),
}
E820 = "HEPTAKERNEL HIA E820 VERIFIED"
RESERVATIONS = "HEPTAKERNEL HIA RESERVATIONS VERIFIED"
BASELINE_DONE = "HEPTAKERNEL HIA PMM PASS"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def text_section(path, out):
    subprocess.run(["objcopy", "-O", "binary", "--only-section=.text",
                    str(Path(path).resolve()), str(out)], check=True)
    return out.read_bytes()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--qemu", default="qemu-system-x86_64")
    args = parser.parse_args()
    report = {
        "schema": "heptakernel.hia-live-pmm-shadow-parent.v2",
        "candidate_scope": "single-CPU TCG HIA-PMM-owned pair; bridge PDE/CR3 effects",
        "linux_full_acceptance": "HOLD",
        "genuine_hia_native_components": ["kernel.hepta", "x86_pt_pair_shadow.hepta",
                                          "x86_shadow_frame_admit.hepta",
                                          "pmm_bitmap_integrity.hepta"],
        "independent_oracle": "CPU data readback, all shadow PTEs, PMM bitmap/free-count and immutable read-only state",
        "atomic_pde_cas": False, "smp_tlb_shootdown": False,
        "dma_exclusion": False, "hia_privilege_backend": False,
        "source_sha256": {
            p: sha(p) for p in ("src/kernel.hepta", "src/x86_pt_pair_shadow.hepta",
                              "src/x86_shadow_frame_admit.hepta", "src/pmm_bitmap_integrity.hepta",
                              "tests/negative/x86_shadow_frame_admit_noop.hepta",
                              "tests/negative/pmm_bitmap_noop.hepta")
        },
        "bridge_sha256": sha("arch/x86_64/boot.S"), "runs": [],
    }
    try:
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            original = text_section("build/x86-shadow-frame-admit.o", folder / "admit-original")
            boot = text_section("build/shadow-owner-admit-boot.o", folder / "admit-boot")
            liar = text_section("build/x86-shadow-frame-admit-unsafe.o", folder / "admit-liar")
            liar_boot = text_section("build/shadow-owner-admit-unsafe-boot.o", folder / "admit-liar-boot")
            builder = text_section("build/x86-pt-pair-shadow.o", folder / "builder-original")
            builder_boot = text_section("build/pt-shadow-boot.o", folder / "builder-boot")
            kernel = text_section("build/kernel.o", folder / "kernel-original")
            bitmap = text_section("build/pmm-bitmap-integrity.o", folder / "bitmap-original")
            bitmap_boot = text_section("build/pmm-bitmap-boot.o", folder / "bitmap-boot")
            bitmap_liar = text_section("build/pmm-bitmap-unsafe.o", folder / "bitmap-liar")
            bitmap_liar_boot = text_section("build/pmm-bitmap-dishonest-boot.o", folder / "bitmap-liar-boot")
            assert all((original, boot, liar, liar_boot, builder, builder_boot,
                        kernel, bitmap, bitmap_boot, bitmap_liar, bitmap_liar_boot))
            assert original == boot and liar == liar_boot and builder == builder_boot
            assert bitmap == bitmap_boot and bitmap_liar == bitmap_liar_boot
            assert original != liar and bitmap != bitmap_liar
            report["native_text_sha256"] = {
                "frame_admit": hashlib.sha256(original).hexdigest(),
                "dishonest_admit": hashlib.sha256(liar).hexdigest(),
                "offline_shadow": hashlib.sha256(builder).hexdigest(),
                "pmm": hashlib.sha256(kernel).hexdigest(),
                "full_bitmap": hashlib.sha256(bitmap).hexdigest(),
                "dishonest_bitmap": hashlib.sha256(bitmap_liar).hexdigest(),
            }
            report["original_object_sha256"] = {
                p: sha(p) for p in ("build/x86-shadow-frame-admit.o", "build/x86-pt-pair-shadow.o",
                                  "build/kernel.o", "build/x86-shadow-frame-admit-unsafe.o",
                                  "build/pmm-bitmap-integrity.o", "build/pmm-bitmap-unsafe.o")
            }
            for mode in CASES:
                linked = text_section(f"build/shadow-owner-{mode}.elf",
                                      folder / ("linked-" + mode))
                selected = liar if mode == "liar" else original
                assert linked.count(selected) == 1, f"{mode}: HIA admission bytes missing/not unique"
                assert linked.count(builder) == 1, f"{mode}: HIA shadow bytes missing/not unique"
                assert linked.count(kernel) == 1, f"{mode}: HIA PMM bytes missing/not unique"
                selected_bitmap = bitmap_liar if mode == "free-liar" else bitmap
                assert linked.count(selected_bitmap) == 1, (
                    f"{mode}: genuine HIA full-PMM checker missing/not unique")
                report[mode + "_linked_hia_text"] = "EXACT_MATCH"

        version = subprocess.run([args.qemu, "--version"], text=True,
                                 capture_output=True, check=True, timeout=10)
        report["qemu_version"] = version.stdout.splitlines()[0]
        for machine, memory_mib in (("pc", 32), ("q35", 64)):
            for mode, (marker, expected_exit) in CASES.items():
                image = Path(f"build/shadow-owner-{mode}-multiboot.elf")
                command = [args.qemu, "-accel", "tcg", "-machine", machine,
                           "-cpu", "qemu64", "-m", str(memory_mib), "-nodefaults",
                           "-display", "none", "-serial", "stdio", "-monitor", "none",
                           "-no-reboot", "-device",
                           "isa-debug-exit,iobase=0xf4,iosize=0x04",
                           "-kernel", str(image)]
                row = {"case": mode, "machine": machine, "memory_mib": memory_mib,
                       "image": str(image), "image_sha256": sha(image), "command": command}
                try:
                    proc = subprocess.run(command, capture_output=True, text=True, timeout=25)
                    row.update(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
                    observed = [k for k, (value, _) in CASES.items()
                                if proc.stdout.count(value) == 1]
                    correct = (
                        proc.returncode == expected_exit and observed == [mode]
                        and proc.stdout.count(E820) == 1
                        and proc.stdout.count(RESERVATIONS) == 1
                        and BASELINE_DONE not in proc.stdout
                    )
                    row["status"] = "PASS" if correct else "FAIL"
                except subprocess.TimeoutExpired as error:
                    row.update(status="TIMEOUT", error=str(error))
                report["runs"].append(row)
        report["status"] = ("PASS" if len(report["runs"]) == 14
                            and all(row["status"] == "PASS" for row in report["runs"])
                            else "FAIL")
    except Exception as error:
        report.update(status="FAIL", error=repr(error))
    Path("build").mkdir(exist_ok=True)
    Path("build/x86-shadow-owner-qemu-report.json").write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
