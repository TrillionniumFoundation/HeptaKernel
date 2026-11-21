SHELL := /bin/sh
HEPTA_COMPILER ?= hia-native-compiler
QEMU ?= qemu-system-x86_64
PYTHON ?= python3
COMPILER_SHA256 := 87c247e4d1c3c9a449d2947fd4227fdc186d519bffd203a04cafce7861a4ed54

.PHONY: test-page-zero test-cr3-root-hw test-x86-cr3-root test-x86-tlb-plan test-pt-downgrade-single-byte test-x86-pt-user-revoke test-pt-report-isolation test-x86-pt-nx-protect test-x86-pt-write-protect test-x86-pt-revoke test-x86-access-gate test-x86-walk4-physical test-x86-walk4-auto test-x86-walk4-huge test-x86-walk4-indexed test-x86-cr3-gate test-cr3-hw test-x86-upper-user all check-compiler test test-x86-pde-2m test-x86-pdpt-1g test-native test-boot test-guard-pages test-memory-map test-arenas test-owner-binding test-reservations test-x86-pte test-x86-pt-commit test-x86-pt-revoke test-x86-pf-gate test-x86-idt test-x86-user-gdt test-x86-tss-gdt test-x86-tss-state test-closure test-linux-inventory record-build full-acceptance clean

all: build/kernel-multiboot.elf

build:
	mkdir -p build

check-compiler:
	@compiler=$$(command -v "$(HEPTA_COMPILER)") || { echo 'Set HEPTA_COMPILER to the pinned compiler; see docs/build.md.' >&2; exit 1; }; \
	printf '%s  %s\n' '$(COMPILER_SHA256)' "$$compiler" | sha256sum -c -

build/kernel.o: src/kernel.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.kernel.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/kernel-host.so: build/kernel.o
	ld -shared -z noexecstack -o "$@" "$<"

build/boot-cases.bin: tests/boot-cases.json tools/pack_boot_cases.py | build
	$(PYTHON) tools/pack_boot_cases.py "$<" "$@"

build/boot.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/e820-boot.o: build/e820-region.o
	objcopy --redefine-sym f0=e820_f0 "$<" "$@"

# Retain exact HIA machine code while exposing its separate boot ABI symbol.
build/arena-boot.o: build/arena-router.o
	objcopy --redefine-sym f0=arena_f0 "$<" "$@"

# Native HIA descriptor/PMM state identity binding; no non-HIA implementation.
build/owner-binding.o: src/owner_binding.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.owner-binding.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/owner-binding.so: build/owner-binding.o
	ld -shared -z noexecstack -o "$@" "$<"

build/owner-boot.o: build/owner-binding.o
	objcopy --redefine-sym f0=owner_f0 "$<" "$@"

# Preserve true native HIA reservation bytecode under a unique boot symbol.
build/reservation-boot.o: build/reservation-gate.o
	objcopy --redefine-sym f0=reservation_f0 "$<" "$@"

# Native HIA writes exactly one leaf in an exclusive caller-owned 4KiB table.
build/x86-pt-commit.o: src/x86_pt_commit.hepta | build check-compiler
	@set -eu; tmp=$(mktemp build/.x86-pt-commit.XXXXXX); trap 'rm -f "$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$tmp"; test -s "$tmp"; \
	test -z "$(nm -u "$tmp")"; mv "$tmp" "$@"

build/x86-pt-commit.so: build/x86-pt-commit.o
	ld -shared -z noexecstack -o "$@" "$<"

build/pt-commit-boot.o: build/x86-pt-commit.o
	objcopy --redefine-sym f0=pt_commit_f0 "$<" "$@"

test-x86-pt-commit: build/x86-pt-commit.so build/e820-allow-all.so
	timeout 90 $(PYTHON) tests/test_x86_pt_commit.py build/x86-pt-commit.so
	$(PYTHON) tests/test_x86_pt_commit.py build/e820-allow-all.so --expect-unsafe

# Native HIA classifier for hardware-captured #PF records; the CPU exception
# entry and CRx/MSR sampling remain non-HIA until upstream backend support.
build/x86-pf-gate.o: src/x86_pf_gate.hepta | build check-compiler
	@set -eu; tmp=$(mktemp build/.x86-pf-gate.XXXXXX); trap 'rm -f "$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$tmp"; test -s "$tmp"; \
	test -z "$(nm -u "$tmp")"; mv "$tmp" "$@"

build/x86-pf-gate.so: build/x86-pf-gate.o
	ld -shared -z noexecstack -o "$@" "$<"

build/pf-gate-boot.o: build/x86-pf-gate.o
	objcopy --redefine-sym f0=pf_gate_f0 "$<" "$@"


test-x86-pf-gate: build/x86-pf-gate.so build/e820-allow-all.so
	timeout 90 $(PYTHON) tests/test_x86_pf_gate.py build/x86-pf-gate.so
	$(PYTHON) tests/test_x86_pf_gate.py build/e820-allow-all.so --expect-unsafe


# HIA native, single-owner IDT descriptor installer (no privileged LIDT yet).
build/x86-idt.o: src/x86_idt_gate.hepta | build check-compiler
	@set -eu; tmp=$(mktemp build/.x86-idt.XXXXXX); trap 'rm -f "$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$tmp"; test -s "$tmp"; \
	test -z "$(nm -u "$tmp")"; mv "$tmp" "$@"

build/x86-idt.so: build/x86-idt.o
	ld -shared -z noexecstack -o "$@" "$<"

build/idt-gate-boot.o: build/x86-idt.o
	objcopy --redefine-sym f0=idt_gate_f0 "$<" "$@"

test-x86-idt: build/x86-idt.so build/e820-allow-all.so
	timeout 90 $(PYTHON) tests/test_x86_idt_gate.py build/x86-idt.so
	$(PYTHON) tests/test_x86_idt_gate.py build/e820-allow-all.so --expect-unsafe


# Native HIA 64-bit TSS descriptor writes the reserved selector 0x20 GDT pair.
build/x86-tss-gdt.o: src/x86_tss_gdt.hepta | build check-compiler
	@set -eu; tmp=$(mktemp build/.x86-tss-gdt.XXXXXX); trap 'rm -f "$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$tmp"; test -s "$tmp"; \
	test -z "$(nm -u "$tmp")"; mv "$tmp" "$@"

build/x86-tss-gdt.so: build/x86-tss-gdt.o
	ld -shared -z noexecstack -o "$@" "$<"

build/tss-gdt-boot.o: build/x86-tss-gdt.o
	objcopy --redefine-sym f0=tss_gdt_f0 "$<" "$@"

test-x86-tss-gdt: build/x86-tss-gdt.so build/e820-allow-all.so
	timeout 90 $(PYTHON) tests/test_x86_tss_gdt.py build/x86-tss-gdt.so
	$(PYTHON) tests/test_x86_tss_gdt.py build/e820-allow-all.so --expect-unsafe

# HIA native CPL3 segment descriptors for the active 64-byte GDT.
build/x86-user-gdt.o: src/x86_user_gdt.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.x86-user-gdt.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/x86-user-gdt.so: build/x86-user-gdt.o
	ld -shared -z noexecstack -o "$@" "$<"

build/user-gdt-boot.o: build/x86-user-gdt.o
	objcopy --redefine-sym f0=user_gdt_f0 "$<" "$@"

test-x86-user-gdt: build/x86-user-gdt.so build/e820-allow-all.so
	timeout 90 $(PYTHON) tests/test_x86_user_gdt.py build/x86-user-gdt.so
	$(PYTHON) tests/test_x86_user_gdt.py build/e820-allow-all.so --expect-unsafe


# Genuine HIA Core v8 native admission of a narrow, caller-supplied single-page
# IRQ/PTE/INVLPG effect sequence. No privileged instruction is emitted.
build/x86-tlb-plan.o: src/x86_tlb_plan.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.x86-tlb-plan.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	set +e; "$(HEPTA_COMPILER)" < "$<" > "$$tmp"; status=$$?; set -e; \
	if test "$$status" -ne 0; then echo "native HIA tlb-plan compiler exit status=$$status (2=invalid source, 3=capacity)" >&2; exit "$$status"; fi; \
	if ! test -s "$$tmp"; then echo "native HIA tlb-plan emitted empty object" >&2; exit 1; fi; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/x86-tlb-plan.so: build/x86-tlb-plan.o
	ld -shared -z noexecstack -o "$@" "$<"

build/x86-tlb-plan-unsafe.o: tests/negative/x86_tlb_plan_allow_all.hepta | build check-compiler
	"$(HEPTA_COMPILER)" < "$<" > "$@"

build/x86-tlb-plan-unsafe.so: build/x86-tlb-plan-unsafe.o
	ld -shared -z noexecstack -o "$@" "$<"

test-x86-tlb-plan: build/x86-tlb-plan.so build/x86-tlb-plan-unsafe.so
	@set -eu; tmp=$$(mktemp build/.tlb-byte-identity.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	env -i PATH= "$(HEPTA_COMPILER)" < src/x86_tlb_plan.hepta > "$$tmp"; \
	cmp "$$tmp" build/x86-tlb-plan.o
	$(PYTHON) tests/test_x86_tlb_plan.py build/x86-tlb-plan.so
	$(PYTHON) tests/test_x86_tlb_plan.py build/x86-tlb-plan-unsafe.so --expect-unsafe

# Real HIA Core v8 2 MiB huge PDE admission, distinct from the 4 KiB PTE writer.
build/x86-pde-2m.o: src/x86_pde_2m.hepta | build check-compiler
	@set -eu; tmp=$(mktemp build/.x86-pde-2m.XXXXXX); trap 'rm -f "$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$tmp"; test -s "$tmp"; \
	test -z "$(nm -u "$tmp")"; mv "$tmp" "$@"

build/x86-pde-2m.so: build/x86-pde-2m.o
	ld -shared -z noexecstack -o "$@" "$<"

build/pde-2m-boot.o: build/x86-pde-2m.o
	objcopy --redefine-sym f0=pde_2m_f0 "$<" "$@"

test-x86-pde-2m: build/x86-pde-2m.so build/e820-allow-all.so
	timeout 90 $(PYTHON) tests/test_x86_pde_2m.py build/x86-pde-2m.so
	$(PYTHON) tests/test_x86_pde_2m.py build/e820-allow-all.so --expect-unsafe

# Native HIA Core v8 1 GiB PDPTE writer (CPUID PDPE1GB required).
# This is a quiescent single-owner table update, not an atomic operation.
build/x86-pdpt-1g.o: src/x86_pdpt_1g.hepta | build check-compiler
	@set -eu; tmp=$(mktemp build/.x86-pdpt-1g.XXXXXX); trap 'rm -f "$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$tmp"; test -s "$tmp"; \
	test -z "$(nm -u "$tmp")"; mv "$tmp" "$@"

build/x86-pdpt-1g.so: build/x86-pdpt-1g.o
	ld -shared -z noexecstack -o "$@" "$<"

test-x86-pdpt-1g: build/x86-pdpt-1g.so build/e820-allow-all.so
	timeout 90 $(PYTHON) tests/test_x86_pdpt_1g.py build/x86-pdpt-1g.so
	$(PYTHON) tests/test_x86_pdpt_1g.py build/e820-allow-all.so --expect-unsafe

# A deliberately stale expected IST1 must fail before HIA GDT and LTR.
build/boot-tss-state-conflict.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_TSS_STATE_CONFLICT=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/tss-state-conflict-multiboot.elf: build/boot-tss-state-conflict.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/tss-state-conflict.elf build/boot-tss-state-conflict.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o
	objcopy -O elf32-i386 build/tss-state-conflict.elf "$@"


# Isolated CPL3->CPL0 RSP0 hardware test; all privileged instructions remain
# the explicit GNU assembly observer, never disguised as a HIA backend.
build/boot-ring3-rsp0.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_RSP0_RING3=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

# Failure injection must be rejected by the genuine HIA huge-page writer.
build/boot-ring3-pde-stale.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_RING3_PDE_STALE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-ring3-rsp0-decoy.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_RSP0_DECOY=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/ring3-rsp0-multiboot.elf: build/boot-ring3-rsp0.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pde-2m-boot.o build/upper-user-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/ring3-rsp0.elf build/boot-ring3-rsp0.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pde-2m-boot.o build/upper-user-boot.o
	objcopy -O elf32-i386 build/ring3-rsp0.elf "$@"

# Hardware CPL3 observation of genuine HIA 4KiB U/S downgrade.
# Privileged IRETQ/INVLPG/IDT remain explicit NON-HIA test-only operations.
build/pt-us-boot.o: build/x86-pt-user-revoke.o
	objcopy --redefine-sym f0=pt_us_f0 "$<" "$@"

build/boot-us-fault.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_US_FAULT=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/us-fault-multiboot.elf: build/boot-us-fault.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pde-2m-boot.o build/upper-user-boot.o build/pt-us-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/us-fault.elf build/boot-us-fault.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pde-2m-boot.o build/upper-user-boot.o build/pt-us-boot.o
	objcopy -O elf32-i386 build/us-fault.elf "$@"

build/boot-us-stale.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_US_STALE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/us-stale-multiboot.elf: build/boot-us-stale.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pde-2m-boot.o build/upper-user-boot.o build/pt-us-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/us-stale.elf build/boot-us-stale.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pde-2m-boot.o build/upper-user-boot.o build/pt-us-boot.o
	objcopy -O elf32-i386 build/us-stale.elf "$@"

build/boot-us-bypass.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_US_BYPASS=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/us-bypass-multiboot.elf: build/boot-us-bypass.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pde-2m-boot.o build/upper-user-boot.o build/pt-us-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/us-bypass.elf build/boot-us-bypass.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pde-2m-boot.o build/upper-user-boot.o build/pt-us-boot.o
	objcopy -O elf32-i386 build/us-bypass.elf "$@"


build/ring3-pde-stale-multiboot.elf: build/boot-ring3-pde-stale.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pde-2m-boot.o build/upper-user-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/ring3-pde-stale.elf build/boot-ring3-pde-stale.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pde-2m-boot.o build/upper-user-boot.o
	objcopy -O elf32-i386 build/ring3-pde-stale.elf "$@"

build/ring3-rsp0-decoy-multiboot.elf: build/boot-ring3-rsp0-decoy.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pde-2m-boot.o build/upper-user-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/ring3-rsp0-decoy.elf build/boot-ring3-rsp0-decoy.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pde-2m-boot.o build/upper-user-boot.o
	objcopy -O elf32-i386 build/ring3-rsp0-decoy.elf "$@"

# Deliberately stale RSP0 refuses the complete native HIA TSS transaction before LTR.
build/boot-tss-rsp0-conflict.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_TSS_RSP0_CONFLICT=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/tss-rsp0-conflict-multiboot.elf: build/boot-tss-rsp0-conflict.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/tss-rsp0-conflict.elf build/boot-tss-rsp0-conflict.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o
	objcopy -O elf32-i386 build/tss-rsp0-conflict.elf "$@"

build/boot-user-gdt-conflict.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_USER_GDT_CONFLICT=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/user-gdt-conflict-multiboot.elf: build/boot-user-gdt-conflict.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/user-gdt-conflict.elf build/boot-user-gdt-conflict.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o
	objcopy -O elf32-i386 build/user-gdt-conflict.elf "$@"

build/boot-tss-conflict.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_TSS_GDT_CONFLICT=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/tss-conflict-multiboot.elf: build/boot-tss-conflict.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/tss-conflict.elf build/boot-tss-conflict.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o
	objcopy -O elf32-i386 build/tss-conflict.elf "$@"

# Exact HIA page-entry encoding under its own x86-64 boot symbol.
build/pte-boot.o: build/x86-pte.o
	objcopy --redefine-sym f0=pte_f0 "$<" "$@"

# Real hardware NX fetch must raise #PF(P=1, I/D=1) at the HIA NX leaf.
# A separate mutation clears only the installed NX bit to prove the fetch
# can execute; the bypass can never pass via a generic exception handler.
build/boot-idt-conflict.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_IDT_CONFLICT=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/idt-conflict-multiboot.elf: build/boot-idt-conflict.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/idt-conflict.elf build/boot-idt-conflict.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o
	objcopy -O elf32-i386 build/idt-conflict.elf "$@"

build/boot-nx-fault.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_NX_FETCH=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-nx-bypass.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_NX_BYPASS=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/nx-fault-multiboot.elf: build/boot-nx-fault.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/nx-fault.elf build/boot-nx-fault.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o
	objcopy -O elf32-i386 build/nx-fault.elf "$@"

build/nx-bypass-multiboot.elf: build/boot-nx-bypass.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/nx-bypass.elf build/boot-nx-bypass.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o
	objcopy -O elf32-i386 build/nx-bypass.elf "$@"


# A genuine NX hardware fault with a deliberately corrupted captured record
# must be rejected by the HIA-native gate instead of accepted by the stub.
build/boot-pf-corrupt.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_NX_FETCH=1 -DHEPTAKERNEL_TEST_PF_RECORD_CORRUPT=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/pf-corrupt-multiboot.elf: build/boot-pf-corrupt.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/pf-corrupt.elf build/boot-pf-corrupt.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o
	objcopy -O elf32-i386 build/pf-corrupt.elf "$@"

# Deliberately stale expected old PTE: genuine native HIA must reject before
# any page-table update or CR3 reload.
build/boot-pt-commit-conflict.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PT_COMMIT_CONFLICT=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/pt-commit-conflict-multiboot.elf: build/boot-pt-commit-conflict.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/pt-commit-conflict.elf build/boot-pt-commit-conflict.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o
	objcopy -O elf32-i386 build/pt-commit-conflict.elf "$@"

# Supervisor CR0.WP enforces a native HIA read-only PTE; the unsafe
# counterpart mutates RW after verifying the original HIA PTE result.
build/boot-wp-fault.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_WP_STORE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-wp-bypass.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_WP_BYPASS=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/wp-fault-multiboot.elf: build/boot-wp-fault.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/wp-fault.elf build/boot-wp-fault.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o
	objcopy -O elf32-i386 build/wp-fault.elf "$@"

build/wp-bypass-multiboot.elf: build/boot-wp-bypass.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/wp-bypass.elf build/boot-wp-bypass.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o
	objcopy -O elf32-i386 build/wp-bypass.elf "$@"

build/boot-pte-unsafe.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_INJECT_PTE_UNSAFE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/pte-unsafe-multiboot.elf: build/boot-pte-unsafe.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/pte-unsafe.elf build/boot-pte-unsafe.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o
	objcopy -O elf32-i386 build/pte-unsafe.elf "$@"

# Deliberately dishonest *native HIA* bypass for negative controls.
build/reservation-unsafe-boot.o: build/e820-allow-all.o
	objcopy --redefine-sym f0=reservation_f0 "$<" "$@"

build/boot-reservation-conflict.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_INJECT_PROTECTED=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/reservation-conflict-multiboot.elf: build/boot-reservation-conflict.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/reservation-conflict.elf build/boot-reservation-conflict.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o
	objcopy -O elf32-i386 build/reservation-conflict.elf "$@"

build/reservation-bypass-multiboot.elf: build/boot-reservation-conflict.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-unsafe-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/reservation-bypass.elf build/boot-reservation-conflict.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-unsafe-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o
	objcopy -O elf32-i386 build/reservation-bypass.elf "$@"

# Independent test-only mutation of the state-pointer ownership bridge.
# It creates a false alias after the genuine HIA router has selected zone B.
build/boot-owner-alias.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_ALIAS_OWNER_STATE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/owner-alias-multiboot.elf: build/boot-owner-alias.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/owner-alias.elf build/boot-owner-alias.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o
	objcopy -O elf32-i386 build/owner-alias.elf "$@"

# Deliberately dishonest HIA router for an end-to-end QEMU negative control.
build/arena-unsafe-boot.o: build/e820-allow-all.o
	objcopy --redefine-sym f0=arena_f0 "$<" "$@"

# Fault-injected boot observer is ONLY for negative-control images.
build/boot-reserved.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_INJECT_RESERVED=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

# Test-only firmware conflict: enabled type-1 RAM with persistent attribute.
build/boot-persistent.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_INJECT_NONVOLATILE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/e820-unsafe-boot.o: build/e820-allow-all.o
	objcopy --redefine-sym f0=e820_f0 "$<" "$@"

build/e820-reserved-multiboot.elf: build/boot-reserved.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/e820-reserved.elf build/boot-reserved.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o
	objcopy -O elf32-i386 build/e820-reserved.elf "$@"

build/e820-bypass-multiboot.elf: build/boot-reserved.o build/kernel.o build/e820-unsafe-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/e820-bypass.elf build/boot-reserved.o build/kernel.o build/e820-unsafe-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o
	objcopy -O elf32-i386 build/e820-bypass.elf "$@"

build/e820-persistent-multiboot.elf: build/boot-persistent.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/e820-persistent.elf build/boot-persistent.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o
	objcopy -O elf32-i386 build/e820-persistent.elf "$@"

build/e820-persistent-bypass-multiboot.elf: build/boot-persistent.o build/kernel.o build/e820-unsafe-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/e820-persistent-bypass.elf build/boot-persistent.o build/kernel.o build/e820-unsafe-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o
	objcopy -O elf32-i386 build/e820-persistent-bypass.elf "$@"

build/arena-bypass-multiboot.elf: build/boot.o build/kernel.o build/e820-boot.o build/arena-unsafe-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/arena-bypass.elf build/boot.o build/kernel.o build/e820-boot.o build/arena-unsafe-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o
	objcopy -O elf32-i386 build/arena-bypass.elf "$@"

build/kernel.elf: build/boot.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o

build/kernel-multiboot.elf: build/kernel.elf
	objcopy -O elf32-i386 "$<" "$@"

test-native: build/kernel-host.so
	timeout 90 $(PYTHON) tests/test_native.py build/kernel-host.so

build/%.o: tests/negative/%.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.negative.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/%-multiboot.elf: build/%.o build/boot.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/$*.elf build/boot.o build/$*.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o
	objcopy -O elf32-i386 build/$*.elf "$@"


# Genuine HIA 2MiB PDE removal after a real memory access; privileged
# INVLPG/IDT/#PF observation remains in the NON-HIA boot bridge.
build/boot-pde-2m-unmap-fault.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PDE_2M_UNMAP_FAULT=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-pde-2m-unmap-stale.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PDE_2M_UNMAP_STALE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-pde-2m-unmap-bypass.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PDE_2M_UNMAP_BYPASS=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

.SECONDARY: build/pde-2m-unmap-fault.elf build/pde-2m-unmap-stale.elf build/pde-2m-unmap-bypass.elf

PDE_2M_UNMAP_SUPPORT := build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pde-2m-boot.o

build/pde-2m-unmap-%.elf: build/boot-pde-2m-unmap-%.o $(PDE_2M_UNMAP_SUPPORT) arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" "$<" $(PDE_2M_UNMAP_SUPPORT)

build/pde-2m-unmap-%-multiboot.elf: build/pde-2m-unmap-%.elf
	objcopy -O elf32-i386 "$<" "$@"

# HIA-native L3 1GiB leaf in three isolated real-MMU experiments.
# QEMU/CPUID/CR3 are explicit NON-HIA test bridges; no Linux capability claim.
build/pdpt-1g-boot.o: build/x86-pdpt-1g.o
	objcopy --redefine-sym f0=pdpt_1g_f0 "$<" "$@"

build/boot-pdpt-1g-hw.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PDPT_1G_HW=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-pdpt-1g-stale.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PDPT_1G_STALE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-pdpt-1g-decoy.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PDPT_1G_DECOY=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

# Isolated HIA 1GiB remove-after-hardware-access: #PF, stale old, bypass.
# The privileged exception/INVLPG mechanism is expressly NON-HIA.
build/boot-pdpt-1g-unmap-fault.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PDPT_1G_UNMAP_FAULT=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-pdpt-1g-unmap-stale.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PDPT_1G_UNMAP_STALE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-pdpt-1g-unmap-bypass.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PDPT_1G_UNMAP_BYPASS=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

.SECONDARY: build/pdpt-1g-hw.elf build/pdpt-1g-stale.elf build/pdpt-1g-decoy.elf build/pdpt-1g-unmap-fault.elf build/pdpt-1g-unmap-stale.elf build/pdpt-1g-unmap-bypass.elf

PDPT_1G_BOOT_SUPPORT := build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pdpt-1g-boot.o

build/pdpt-1g-%.elf: build/boot-pdpt-1g-%.o $(PDPT_1G_BOOT_SUPPORT) arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" "$<" $(PDPT_1G_BOOT_SUPPORT)

build/pdpt-1g-%-multiboot.elf: build/pdpt-1g-%.elf
	objcopy -O elf32-i386 "$<" "$@"

test-boot: test-elf64-page-plan-hw test-elf64-page-hw test-pmm-bitmap-hw test-cow-frame-binding-hw test-cow-integrated-hw test-cow-pte-hw test-cow-split-hw test-cow-refcount-hw test-page-copy-hw test-page-zero-hw build/pde-2m-unmap-fault-multiboot.elf build/pde-2m-unmap-stale-multiboot.elf build/pde-2m-unmap-bypass-multiboot.elf build/pdpt-1g-unmap-fault-multiboot.elf build/pdpt-1g-unmap-stale-multiboot.elf build/pdpt-1g-unmap-bypass-multiboot.elf build/pdpt-1g-hw-multiboot.elf build/pdpt-1g-stale-multiboot.elf build/pdpt-1g-decoy-multiboot.elf build/us-fault-multiboot.elf build/us-stale-multiboot.elf build/us-bypass-multiboot.elf build/pt-nx-fault-multiboot.elf build/pt-nx-stale-multiboot.elf build/pt-nx-bypass-multiboot.elf build/pt-protect-fault-multiboot.elf build/pt-protect-stale-multiboot.elf build/pt-protect-bypass-multiboot.elf build/pt-revoke-fault-multiboot.elf build/pt-revoke-stale-multiboot.elf build/pt-revoke-bypass-multiboot.elf build/ring3-upper-stale-multiboot.elf build/user-gdt-conflict-multiboot.elf build/ring3-rsp0-multiboot.elf build/ring3-rsp0-decoy-multiboot.elf build/tss-rsp0-conflict-multiboot.elf build/tss-state-conflict-multiboot.elf build/tss-conflict-multiboot.elf build/idt-conflict-multiboot.elf build/pf-corrupt-multiboot.elf build/pt-commit-conflict-multiboot.elf build/wp-fault-multiboot.elf build/wp-bypass-multiboot.elf build/nx-fault-multiboot.elf build/nx-bypass-multiboot.elf build/pte-unsafe-multiboot.elf build/reservation-conflict-multiboot.elf build/reservation-bypass-multiboot.elf build/owner-alias-multiboot.elf build/arena-bypass-multiboot.elf build/kernel-multiboot.elf build/success_stub-multiboot.elf build/bounds_trap-multiboot.elf build/e820-reserved-multiboot.elf build/e820-bypass-multiboot.elf build/e820-persistent-multiboot.elf build/e820-persistent-bypass-multiboot.elf build/ring3-pde-stale-multiboot.elf test-cr3-hw
	$(PYTHON) tests/test_boot.py --qemu "$(QEMU)"

test-guard-pages: build/kernel-host.so
	timeout 30 $(PYTHON) tests/test_guard_pages.py build/kernel-host.so

# The E820 source is independently compiled and its exact machine code
# is linked into the QEMU kernel under the distinct e820_f0 symbol.
build/e820-region.o: src/e820_region.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.e820-region.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/e820-region.so: build/e820-region.o
	ld -shared -z noexecstack -o "$@" "$<"

build/e820-allow-all.o: tests/negative/e820_allow_all.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.e820-negative.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/e820-allow-all.so: build/e820-allow-all.o
	ld -shared -z noexecstack -o "$@" "$<"

test-memory-map: build/e820-region.so build/e820-allow-all.so
	timeout 60 $(PYTHON) tests/test_e820_region.py build/e820-region.so
	$(PYTHON) tests/test_e820_region.py build/e820-allow-all.so --expect-unsafe

# Bounded read-only HIA arena geometry and ownership routing.
build/arena-router.o: src/arena_router.hepta | build check-compiler
	@set -eu; tmp=$(mktemp build/.arena-router.XXXXXX); trap 'rm -f "$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$tmp"; test -s "$tmp"; \
	test -z "$(nm -u "$tmp")"; mv "$tmp" "$@"

build/arena-router.so: build/arena-router.o
	ld -shared -z noexecstack -o "$@" "$<"

test-arenas: build/arena-router.so build/e820-allow-all.so
	timeout 90 $(PYTHON) tests/test_arena_router.py build/arena-router.so
	$(PYTHON) tests/test_arena_router.py build/e820-allow-all.so --expect-unsafe

# Genuine PMM INIT feeds a separately compiled HIA descriptor/state gate.
test-owner-binding: build/owner-binding.so build/kernel-host.so build/e820-allow-all.so
	$(PYTHON) tests/test_owner_binding_capabilities.py "$(HEPTA_COMPILER)"
	timeout 90 $(PYTHON) tests/test_owner_binding.py build/owner-binding.so build/kernel-host.so
	$(PYTHON) tests/test_owner_binding.py build/e820-allow-all.so build/kernel-host.so --expect-unsafe

# An independent native HIA suffix-reservation precondition; no assembly stub.
build/reservation-gate.o: src/reservation_gate.hepta | build check-compiler
	@set -eu; tmp=$(mktemp build/.reservation.XXXXXX); trap 'rm -f "$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$tmp"; test -s "$tmp"; \
	test -z "$(nm -u "$tmp")"; mv "$tmp" "$@"

build/reservation-gate.so: build/reservation-gate.o
	ld -shared -z noexecstack -o "$@" "$<"

test-reservations: build/reservation-gate.so build/e820-allow-all.so
	timeout 90 $(PYTHON) tests/test_reservation_gate.py build/reservation-gate.so
	$(PYTHON) tests/test_reservation_gate.py build/e820-allow-all.so --expect-unsafe


# Native HIA TSS RSP0/IST1/IOPB transactional provisioning, prior to privileged LTR.
build/x86-tss-state.o: src/x86_tss_state.hepta | build check-compiler
	@set -eu; tmp=$(mktemp build/.x86-tss-state.XXXXXX); trap 'rm -f "$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$tmp"; test -s "$tmp"; \
	test -z "$(nm -u "$tmp")"; mv "$tmp" "$@"

build/x86-tss-state.so: build/x86-tss-state.o
	ld -shared -z noexecstack -o "$@" "$<"

build/tss-state-boot.o: build/x86-tss-state.o
	objcopy --redefine-sym f0=tss_state_f0 "$<" "$@"

test-x86-tss-state: build/x86-tss-state.so build/e820-allow-all.so
	timeout 90 $(PYTHON) tests/test_x86_tss_state.py build/x86-tss-state.so
	$(PYTHON) tests/test_x86_tss_state.py build/e820-allow-all.so --expect-unsafe

# Genuine HIA 4KiB x86-64 PTE policy encoder; native tests, not MMU activation.
build/x86-pte.o: src/x86_pte_leaf.hepta | build check-compiler
	@set -eu; tmp=$(mktemp build/.x86-pte.XXXXXX); trap 'rm -f "$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$tmp"; test -s "$tmp"; \
	test -z "$(nm -u "$tmp")"; mv "$tmp" "$@"

build/x86-pte.so: build/x86-pte.o
	ld -shared -z noexecstack -o "$@" "$<"

test-x86-pte: build/x86-pte.so build/e820-allow-all.so
	timeout 90 $(PYTHON) tests/test_x86_pte_leaf.py build/x86-pte.so
	$(PYTHON) tests/test_x86_pte_leaf.py build/e820-allow-all.so --expect-unsafe

record-build: build/pde-2m-unmap-fault-multiboot.elf build/pde-2m-unmap-stale-multiboot.elf build/pde-2m-unmap-bypass-multiboot.elf build/us-fault-multiboot.elf build/us-stale-multiboot.elf build/us-bypass-multiboot.elf build/x86-pt-user-revoke.so build/x86-pt-user-revoke.o build/pt-nx-fault-multiboot.elf build/pt-nx-stale-multiboot.elf build/pt-nx-bypass-multiboot.elf build/pt-nx-boot.o build/x86-pt-nx-protect.so build/x86-pt-nx-protect.o build/pt-protect-boot.o build/pt-protect-fault-multiboot.elf build/pt-protect-stale-multiboot.elf build/pt-protect-bypass-multiboot.elf build/x86-pt-write-protect.so build/x86-pt-write-protect.o build/pt-revoke-boot.o build/pt-revoke-fault-multiboot.elf build/pt-revoke-stale-multiboot.elf build/pt-revoke-bypass-multiboot.elf build/upper-user-boot.o build/ring3-upper-stale-multiboot.elf build/x86-upper-user.so build/x86-user-gdt.so build/user-gdt-boot.o build/boot-user-gdt-conflict.o build/user-gdt-conflict-multiboot.elf build/boot-ring3-rsp0.o build/boot-ring3-rsp0-decoy.o build/ring3-rsp0-multiboot.elf build/ring3-rsp0-decoy-multiboot.elf build/boot-tss-rsp0-conflict.o build/tss-rsp0-conflict-multiboot.elf build/boot-tss-state-conflict.o build/tss-state-conflict-multiboot.elf build/boot-tss-conflict.o build/tss-conflict-multiboot.elf build/x86-tss-gdt.so build/boot-idt-conflict.o build/idt-conflict-multiboot.elf build/idt-gate-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/x86-idt.so build/pf-corrupt-multiboot.elf build/boot-pf-corrupt.o build/x86-pf-gate.so build/pf-gate-boot.o build/pt-commit-conflict-multiboot.elf build/x86-pt-commit.so build/wp-fault-multiboot.elf build/wp-bypass-multiboot.elf build/nx-fault-multiboot.elf build/nx-bypass-multiboot.elf build/pte-unsafe-multiboot.elf build/pte-boot.o build/pt-commit-boot.o build/x86-pte.so build/reservation-conflict-multiboot.elf build/reservation-bypass-multiboot.elf build/reservation-gate.so build/owner-binding.so build/owner-boot.o build/owner-alias-multiboot.elf build/arena-bypass-multiboot.elf build/arena-router.so build/kernel-host.so build/kernel-multiboot.elf build/e820-reserved-multiboot.elf build/e820-bypass-multiboot.elf build/e820-persistent-multiboot.elf build/e820-persistent-bypass-multiboot.elf build/x86-pde-2m.o build/x86-pde-2m.so build/x86-pdpt-1g.o build/x86-pdpt-1g.so build/pde-2m-boot.o build/boot-ring3-pde-stale.o build/ring3-pde-stale-multiboot.elf
	$(PYTHON) tools/record_build.py --compiler "$(HEPTA_COMPILER)"

# Check that both independent native oracles published non-overlapping,
# exact-source and exact-library-bound evidence (including hostile reports).
test-pt-report-isolation: test-x86-pt-nx-protect test-x86-pt-write-protect
	$(PYTHON) tests/test_pt_downgrade_report_isolation.py

# Guard against live leaf permission changes writing eight PTE bytes.
# Native differential oracles and QEMU hardware cases remain independently required.
test-pt-downgrade-single-byte:
	$(PYTHON) -m unittest tests.test_pt_downgrade_single_byte -v

test-closure:
	$(PYTHON) tests/test_closure.py

test-linux-inventory:
	$(PYTHON) tests/test_linux_inventory.py
	$(PYTHON) tests/test_linux_x86_syscall_matrix.py
	$(PYTHON) tests/test_linux_kconfig_relations.py
	$(PYTHON) tests/test_linux_kconfig_scoped.py
	$(PYTHON) tests/test_linux_kconfig_include_targets.py

test: test-x86-shadow-frame-admit test-x86-pt-pair test-elf64-snapshot test-elf64-page-plan-hw test-elf64-page-hw test-elf64-page-plan test-elf64-page-fill test-elf64-load-segments test-elf64-exec-admit test-pmm-bitmap-integrity test-cow-frame-binding test-cow-abort-pte-guarded test-cow-abort test-cow-pte-swap test-cow-split test-cow-refcount test-page-copy test-page-zero test-cr3-root-hw test-x86-cr3-root test-x86-tlb-plan test-pt-downgrade-single-byte test-x86-pt-user-revoke test-pt-report-isolation test-x86-pt-nx-protect test-x86-pt-write-protect test-x86-pt-revoke test-x86-access-gate test-x86-walk4-physical test-x86-walk4-auto test-x86-walk4-huge test-x86-walk4-indexed test-x86-walk4 test-x86-cr3-gate test-cr3-hw test-x86-upper-user test-x86-pde-2m test-x86-pdpt-1g test-x86-user-gdt test-x86-tss-state test-x86-tss-gdt test-native test-guard-pages test-memory-map test-arenas test-owner-binding test-reservations test-x86-pte test-x86-pt-commit test-x86-pf-gate test-x86-idt test-boot test-closure test-linux-inventory record-build

# Genuine native HIA single-owner upper-level user-access transition.
build/x86-upper-user.o: src/x86_upper_user_gate.hepta | build check-compiler
	@set -eu; tmp=$(mktemp build/.x86-upper-user.XXXXXX); trap 'rm -f "$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$tmp"; test -s "$tmp"; \
	test -z "$(nm -u "$tmp")"; mv "$tmp" "$@"

build/x86-upper-user.so: build/x86-upper-user.o
	ld -shared -z noexecstack -o "$@" "$<"

test-x86-upper-user: build/x86-upper-user.so build/e820-allow-all.so
	timeout 90 $(PYTHON) tests/test_x86_upper_user_gate.py build/x86-upper-user.so
	$(PYTHON) tests/test_x86_upper_user_gate.py build/e820-allow-all.so --expect-unsafe

# Symbol-only native-HIA machine code rename for isolated ring3 hardware path.
build/upper-user-boot.o: build/x86-upper-user.o
	objcopy --redefine-sym f0=upper_user_f0 "$<" "$@"

# Stale PML4E expected-old HIA denial, before CPL3 entry.
build/boot-ring3-upper-stale.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_RING3_UPPER_STALE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/ring3-upper-stale-multiboot.elf: build/boot-ring3-upper-stale.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pde-2m-boot.o build/upper-user-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/ring3-upper-stale.elf build/boot-ring3-upper-stale.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pde-2m-boot.o build/upper-user-boot.o
	objcopy -O elf32-i386 build/ring3-upper-stale.elf "$@"

# Genuine HIA read-only 4KiB source -> exclusive mutable destination copy.
build/page-copy.o: src/page_copy.hepta | build check-compiler
	@set -eu; tmp=$(mktemp build/.page-copy.XXXXXX); trap 'rm -f "$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$tmp"; test -s "$tmp"; \
	test -z "$(nm -u "$tmp")"; mv "$tmp" "$@"

build/page-copy.so: build/page-copy.o
	ld -shared -z noexecstack -o "$@" "$<"

build/page-copy-unsafe.o: tests/negative/page_copy_noop.hepta | build check-compiler
	"$(HEPTA_COMPILER)" < "$<" > "$@"

build/page-copy-unsafe.so: build/page-copy-unsafe.o
	ld -shared -z noexecstack -o "$@" "$<"

.PHONY: test-page-copy
test-page-copy: build/page-copy.so build/page-copy-unsafe.so
	@set -eu; tmp=$(mktemp build/.copy-byte-identity.XXXXXX); trap 'rm -f "$tmp"' EXIT HUP INT TERM; \
	env -i PATH= "$(HEPTA_COMPILER)" < src/page_copy.hepta > "$tmp"; \
	cmp "$tmp" build/page-copy.o
	timeout 90 $(PYTHON) tests/test_page_copy.py build/page-copy.so
	$(PYTHON) tests/test_page_copy.py build/page-copy-unsafe.so --expect-unsafe

full-acceptance:
	$(PYTHON) tools/check_closure.py

clean:
	rm -rf build build/x86-user-gdt.o build/x86-user-gdt.so build/user-gdt-boot.o build/user-gdt-conflict.elf build/user-gdt-conflict-multiboot.elf build/boot-user-gdt-conflict.o


# Actual HIA Core v8 restricted CR3 long-mode state admission predicate.
# This does not emit/execute privileged MOV CR3 or change TLB hardware.
build/x86-cr3-gate.o: src/x86_cr3_gate.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.x86-cr3-gate.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/x86-cr3-gate.so: build/x86-cr3-gate.o
	ld -shared -z noexecstack -o "$@" "$<"

build/cr3-allow-all.o: tests/negative/cr3_allow_all.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.cr3-allow-all.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/cr3-allow-all.so: build/cr3-allow-all.o
	ld -shared -z noexecstack -o "$@" "$<"

test-x86-cr3-gate: build/x86-cr3-gate.so build/cr3-allow-all.so
	timeout 90 $(PYTHON) tests/test_x86_cr3_gate.py build/x86-cr3-gate.so --object build/x86-cr3-gate.o
	$(PYTHON) tests/test_x86_cr3_gate.py build/cr3-allow-all.so --expect-unsafe


# The privileged hardware state sampler is intentionally NON-HIA. This
# experiment calls unmodified native HIA Core v8 bytes and never writes CR3.
build/cr3-boot.o: build/x86-cr3-gate.o
	objcopy --redefine-sym cr3_admit=cr3_probe_f0 "$<" "$@"

build/cr3-unsafe-boot.o: build/cr3-allow-all.o
	objcopy --redefine-sym cr3_allow_all=cr3_probe_f0 "$<" "$@"

build/boot-cr3-live.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_CR3_LIVE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-cr3-unsafe.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_CR3_UNSAFE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

CR3_HW_SUPPORT := build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o

build/cr3-live.elf: build/boot-cr3-live.o $(CR3_HW_SUPPORT) build/cr3-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cr3-live.o $(CR3_HW_SUPPORT) build/cr3-boot.o

build/cr3-unsafe.elf: build/boot-cr3-unsafe.o $(CR3_HW_SUPPORT) build/cr3-unsafe-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cr3-unsafe.o $(CR3_HW_SUPPORT) build/cr3-unsafe-boot.o

build/cr3-%-multiboot.elf: build/cr3-%.elf
	objcopy -O elf32-i386 "$<" "$@"

test-cr3-hw: build/cr3-live-multiboot.elf build/cr3-unsafe-multiboot.elf
	$(PYTHON) tests/test_cr3_qemu.py --qemu "$(QEMU)"

# Genuine HIA native four-level 4KiB supplied-entry translation/policy.
build/x86-walk4.o: src/x86_walk4_entries.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.x86-walk4.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/x86-walk4.so: build/x86-walk4.o
	ld -shared -z noexecstack -o "$@" "$<"

build/x86-walk4-unsafe.o: tests/negative/walk4_allow_all.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.x86-walk4-unsafe.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/x86-walk4-unsafe.so: build/x86-walk4-unsafe.o
	ld -shared -z noexecstack -o "$@" "$<"

.PHONY: test-x86-walk4
test-x86-walk4: build/x86-walk4.so build/x86-walk4-unsafe.so
	timeout 90 $(PYTHON) tests/test_x86_walk4_entries.py build/x86-walk4.so --object build/x86-walk4.o
	$(PYTHON) tests/test_x86_walk4_entries.py build/x86-walk4-unsafe.so --expect-unsafe

# Native HIA four-level index extraction and parent-link checking on four
# caller-supplied 4KiB table snapshots; not a hardware CR3 page walk.
build/x86-walk4-indexed.o: src/x86_walk4_indexed.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.x86-walk4-indexed.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/x86-walk4-indexed.so: build/x86-walk4-indexed.o
	ld -shared -z noexecstack -o "$@" "$<"

build/x86-walk4-indexed-unsafe.o: tests/negative/walk4_indexed_allow_all.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.x86-walk4-indexed-unsafe.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/x86-walk4-indexed-unsafe.so: build/x86-walk4-indexed-unsafe.o
	ld -shared -z noexecstack -o "$@" "$<"

test-x86-walk4-indexed: build/x86-walk4-indexed.so build/x86-walk4-indexed-unsafe.so
	timeout 90 $(PYTHON) tests/test_x86_walk4_indexed.py build/x86-walk4-indexed.so --object build/x86-walk4-indexed.o
	$(PYTHON) tests/test_x86_walk4_indexed.py build/x86-walk4-indexed-unsafe.so --expect-unsafe

# Genuine HIA Core v8 supplied-entry 2MiB/1GiB page translation, independent
# oracle, and dishonest HIA negative control (no hardware CR3/MMU claims).
build/x86-walk4-huge.o: src/x86_walk4_huge.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.x86-walk4-huge.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/x86-walk4-huge.so: build/x86-walk4-huge.o
	ld -shared -z noexecstack -o "$@" "$<"

build/x86-walk4-huge-unsafe.o: tests/negative/walk4_huge_allow_all.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.x86-walk4-huge-unsafe.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/x86-walk4-huge-unsafe.so: build/x86-walk4-huge-unsafe.o
	ld -shared -z noexecstack -o "$@" "$<"

test-x86-walk4-huge: build/x86-walk4-huge.so build/x86-walk4-huge-unsafe.so
	timeout 90 $(PYTHON) tests/test_x86_walk4_huge.py build/x86-walk4-huge.so --object build/x86-walk4-huge.o
	$(PYTHON) tests/test_x86_walk4_huge.py build/x86-walk4-huge-unsafe.so --expect-unsafe


# Genuine HIA CR3-rooted walk through a permutable copied physical window.
# Not authenticated RAM, a hardware CR3 read, or a concurrent MMU manager.
build/x86-walk4-physical.o: src/x86_walk4_physical.hepta | build check-compiler
	@set -eu; tmp=$(mktemp build/.x86-walk4-physical.XXXXXX); trap 'rm -f "$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$tmp"; test -s "$tmp"; \
	test -z "$(nm -u "$tmp")"; mv "$tmp" "$@"

build/x86-walk4-physical.so: build/x86-walk4-physical.o
	ld -shared -z noexecstack -o "$@" "$<"

test-x86-walk4-physical: build/x86-walk4-physical.so build/x86-walk4-indexed-unsafe.so
	timeout 90 $(PYTHON) tests/test_x86_walk4_physical.py build/x86-walk4-physical.so --object build/x86-walk4-physical.o
	$(PYTHON) tests/test_x86_walk4_physical.py build/x86-walk4-indexed-unsafe.so --expect-unsafe

# Genuine HIA indexed page snapshots; CPU PS bits select 4KiB/2MiB/1GiB.
build/x86-walk4-auto.o: src/x86_walk4_auto.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.x86-walk4-auto.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/x86-walk4-auto.so: build/x86-walk4-auto.o
	ld -shared -z noexecstack -o "$@" "$<"

test-x86-walk4-auto: build/x86-walk4-auto.so build/x86-walk4-indexed-unsafe.so
	timeout 90 $(PYTHON) tests/test_x86_walk4_auto.py build/x86-walk4-auto.so --object build/x86-walk4-auto.o
	$(PYTHON) tests/test_x86_walk4_auto.py build/x86-walk4-indexed-unsafe.so --expect-unsafe

# Native HIA effective paging rights for CPL0/CPL3, WP, SMEP, SMAP and NXE.
build/x86-access-gate.o: src/x86_access_gate.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.x86-access-gate.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/x86-access-gate.so: build/x86-access-gate.o
	ld -shared -z noexecstack -o "$@" "$<"

build/x86-access-unsafe.o: tests/negative/x86_access_allow_all.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.x86-access-unsafe.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/x86-access-unsafe.so: build/x86-access-unsafe.o
	ld -shared -z noexecstack -o "$@" "$<"

test-x86-access-gate: build/x86-access-gate.so build/x86-access-unsafe.so build/x86-walk4-physical.so
	timeout 90 $(PYTHON) tests/test_x86_access_gate.py build/x86-access-gate.so --object build/x86-access-gate.o --walk-library build/x86-walk4-physical.so
	$(PYTHON) tests/test_x86_access_gate.py build/x86-access-unsafe.so --expect-unsafe


# Genuine native HIA PTE removal linked into isolated hardware observers.
build/pt-revoke-boot.o: build/x86-pt-revoke.o
	objcopy --redefine-sym f0=pt_revoke_f0 "$<" "$@"

build/boot-pt-revoke-fault.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PT_REVOKE_FAULT=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/pt-revoke-fault-multiboot.elf: build/boot-pt-revoke-fault.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pt-revoke-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/pt-revoke-fault.elf build/boot-pt-revoke-fault.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pt-revoke-boot.o
	objcopy -O elf32-i386 build/pt-revoke-fault.elf "$@"

build/boot-pt-revoke-stale.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PT_REVOKE_STALE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/pt-revoke-stale-multiboot.elf: build/boot-pt-revoke-stale.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pt-revoke-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/pt-revoke-stale.elf build/boot-pt-revoke-stale.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pt-revoke-boot.o
	objcopy -O elf32-i386 build/pt-revoke-stale.elf "$@"

build/boot-pt-revoke-bypass.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PT_REVOKE_BYPASS=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/pt-revoke-bypass-multiboot.elf: build/boot-pt-revoke-bypass.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pt-revoke-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/pt-revoke-bypass.elf build/boot-pt-revoke-bypass.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pt-revoke-boot.o
	objcopy -O elf32-i386 build/pt-revoke-bypass.elf "$@"


# Genuine HIA RW->RO PTE writer: live QEMU fault plus independent stale and
# deliberately restored-RW controls. INVLPG and #PF entry remain non-HIA.
build/pt-protect-boot.o: build/x86-pt-write-protect.o
	objcopy --redefine-sym f0=pt_protect_f0 "$<" "$@"

build/boot-pt-protect-fault.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PT_PROTECT_FAULT=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-pt-protect-stale.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PT_PROTECT_STALE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-pt-protect-bypass.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PT_PROTECT_BYPASS=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/pt-protect-fault-multiboot.elf: build/boot-pt-protect-fault.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pt-protect-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/pt-protect-fault.elf build/boot-pt-protect-fault.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pt-protect-boot.o
	objcopy -O elf32-i386 build/pt-protect-fault.elf "$@"

build/pt-protect-stale-multiboot.elf: build/boot-pt-protect-stale.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pt-protect-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/pt-protect-stale.elf build/boot-pt-protect-stale.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pt-protect-boot.o
	objcopy -O elf32-i386 build/pt-protect-stale.elf "$@"

build/pt-protect-bypass-multiboot.elf: build/boot-pt-protect-bypass.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pt-protect-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/pt-protect-bypass.elf build/boot-pt-protect-bypass.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pt-protect-boot.o
	objcopy -O elf32-i386 build/pt-protect-bypass.elf "$@"

# Native HIA clears a single 4KiB leaf under a quiescent exclusive owner;
# no hardware INVLPG, TLB shootdown or concurrent CAS is implemented.
build/x86-pt-revoke.o: src/x86_pt_revoke.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.x86-pt-revoke.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/x86-pt-revoke.so: build/x86-pt-revoke.o
	ld -shared -z noexecstack -o "$@" "$<"

build/x86-pt-revoke-unsafe.o: tests/negative/x86_pt_revoke_allow_all.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.x86-pt-revoke-unsafe.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/x86-pt-revoke-unsafe.so: build/x86-pt-revoke-unsafe.o
	ld -shared -z noexecstack -o "$@" "$<"

test-x86-pt-revoke: build/x86-pt-revoke.so build/x86-pt-revoke-unsafe.so
	timeout 90 $(PYTHON) tests/test_x86_pt_revoke.py build/x86-pt-revoke.so
	$(PYTHON) tests/test_x86_pt_revoke.py build/x86-pt-revoke-unsafe.so --expect-unsafe

# Native HIA exact-old quiescent downgrade; never claim SMP atomicity/TLB flush.
build/x86-pt-write-protect.o: src/x86_pt_write_protect.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.x86-pt-write-protect.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/x86-pt-write-protect.so: build/x86-pt-write-protect.o
	ld -shared -z noexecstack -o "$@" "$<"

build/x86-pt-write-protect-unsafe.o: tests/negative/x86_pt_write_protect_allow_all.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.x86-pt-write-protect-unsafe.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/x86-pt-write-protect-unsafe.so: build/x86-pt-write-protect-unsafe.o
	ld -shared -z noexecstack -o "$@" "$<"

test-x86-pt-write-protect: build/x86-pt-write-protect.so build/x86-pt-write-protect-unsafe.so
	timeout 90 $(PYTHON) tests/test_x86_pt_write_protect.py build/x86-pt-write-protect.so
	$(PYTHON) tests/test_x86_pt_write_protect.py build/x86-pt-write-protect-unsafe.so --expect-unsafe

# Genuine native HIA RX->NX transition hardware experiments on PC/Q35.
# Privileged INVLPG and exception entry remain in the non-HIA test bridge.
build/pt-nx-boot.o: build/x86-pt-nx-protect.o
	objcopy --redefine-sym f0=pt_nx_f0 "$<" "$@"

build/boot-pt-nx-fault.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PT_NX_FAULT=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/pt-nx-fault-multiboot.elf: build/boot-pt-nx-fault.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pt-nx-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/pt-nx-fault.elf build/boot-pt-nx-fault.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pt-nx-boot.o
	objcopy -O elf32-i386 build/pt-nx-fault.elf "$@"

build/boot-pt-nx-stale.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PT_NX_STALE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/pt-nx-stale-multiboot.elf: build/boot-pt-nx-stale.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pt-nx-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/pt-nx-stale.elf build/boot-pt-nx-stale.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pt-nx-boot.o
	objcopy -O elf32-i386 build/pt-nx-stale.elf "$@"

build/boot-pt-nx-bypass.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PT_NX_BYPASS=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/pt-nx-bypass-multiboot.elf: build/boot-pt-nx-bypass.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pt-nx-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/pt-nx-bypass.elf build/boot-pt-nx-bypass.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pt-nx-boot.o
	objcopy -O elf32-i386 build/pt-nx-bypass.elf "$@"

# Genuine HIA single-owner RX->R/NX PTE execute-disable; no privileged TLB op.
build/x86-pt-nx-protect.o: src/x86_pt_nx_protect.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.x86-pt-nx-protect.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/x86-pt-nx-protect.so: build/x86-pt-nx-protect.o
	ld -shared -z noexecstack -o "$@" "$<"

build/x86-pt-nx-protect-unsafe.o: tests/negative/x86_pt_nx_protect_allow_all.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.x86-pt-nx-unsafe.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/x86-pt-nx-protect-unsafe.so: build/x86-pt-nx-protect-unsafe.o
	ld -shared -z noexecstack -o "$@" "$<"

test-x86-pt-nx-protect: build/x86-pt-nx-protect.so build/x86-pt-nx-protect-unsafe.so
	timeout 90 $(PYTHON) tests/test_x86_pt_nx_protect.py build/x86-pt-nx-protect.so
	$(PYTHON) tests/test_x86_pt_nx_protect.py build/x86-pt-nx-protect-unsafe.so --expect-unsafe

# Genuine HIA single-owner 4KiB user-to-supervisor PTE downgrade.
# This does not establish TLB shootdown, hardware ring-3 fault, or atomicity.
build/x86-pt-user-revoke.o: src/x86_pt_user_revoke.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.x86-pt-user-revoke.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/x86-pt-user-revoke.so: build/x86-pt-user-revoke.o
	ld -shared -z noexecstack -o "$@" "$<"

build/x86-pt-user-revoke-unsafe.o: tests/negative/x86_pt_user_revoke_allow_all.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.x86-pt-user-revoke-unsafe.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/x86-pt-user-revoke-unsafe.so: build/x86-pt-user-revoke-unsafe.o
	ld -shared -z noexecstack -o "$@" "$<"

test-x86-pt-user-revoke: build/x86-pt-user-revoke.so build/x86-pt-user-revoke-unsafe.so
	timeout 90 $(PYTHON) tests/test_x86_pt_user_revoke.py build/x86-pt-user-revoke.so
	$(PYTHON) tests/test_x86_pt_user_revoke.py build/x86-pt-user-revoke-unsafe.so --expect-unsafe


# Native HIA PML4 root-page read-only admission; not authenticated physical RAM.
build/x86-cr3-root.o: src/x86_cr3_root.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.x86-cr3-root.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/x86-cr3-root.so: build/x86-cr3-root.o
	ld -shared -z noexecstack -o "$@" "$<"

build/x86-cr3-root-unsafe.o: tests/negative/x86_cr3_root_allow_all.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.x86-cr3-root-unsafe.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/x86-cr3-root-unsafe.so: build/x86-cr3-root-unsafe.o
	ld -shared -z noexecstack -o "$@" "$<"

test-x86-cr3-root: build/x86-cr3-root.so build/x86-cr3-root-unsafe.so
	@set -eu; tmp=$$(mktemp build/.x86-cr3-root-byte-identity.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	env -i PATH= "$(HEPTA_COMPILER)" < src/x86_cr3_root.hepta > "$$tmp"; \
	cmp "$$tmp" build/x86-cr3-root.o
	timeout 90 $(PYTHON) tests/test_x86_cr3_root.py build/x86-cr3-root.so
	$(PYTHON) tests/test_x86_cr3_root.py build/x86-cr3-root-unsafe.so --expect-unsafe
	@set -eux; bad=$$(mktemp build/.x86-root-readonly-negative.XXXXXX); good=$$(mktemp build/.x86-root-mutable-positive.XXXXXX); \
	  source=$$(mktemp build/.x86-root-mutable-source.XXXXXX); trap 'rm -f "$$bad" "$$good" "$$source"' EXIT HUP INT TERM; \
	  set +e; env -i PATH= "$(HEPTA_COMPILER)" < tests/negative/x86_cr3_root_readonly_store.hepta > "$$bad"; status=$$?; set -e; \
	  test "$$status" -eq 2 && test ! -s "$$bad" || { echo "readonly root store not rejected with invalid-source status=2" >&2; exit 1; }; \
	  sed 's/_ = buffer.store(root,index,zero)/ignored:u8 = buffer.load(root,index)/g' tests/negative/x86_cr3_root_readonly_store.hepta > "$$source"; \
	  env -i PATH= "$(HEPTA_COMPILER)" < "$$source" > "$$good"; test -s "$$good"; \
	  test -z "$$(nm -u "$$good")"; echo "read-only loan store rejected; otherwise-identical read-only helper compiled"

# Isolated CR3-root hardware observer: CPUID/MOV CR3 remain NON-HIA.
build/root-native-boot.o: build/x86-cr3-root.o
	objcopy --redefine-sym f0=root_native_f0 "$<" "$@"
build/root-unsafe-native-boot.o: build/x86-cr3-root-unsafe.o
	objcopy --redefine-sym f0=root_native_f0 "$<" "$@"
build/boot-root-live.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_ROOT_LIVE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-root-unsafe.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_ROOT_UNSAFE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-root-spoof.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_ROOT_SPOOF=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
ROOT_HW_SUPPORT := build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o
build/root-live.elf: build/boot-root-live.o $(ROOT_HW_SUPPORT) build/root-native-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-root-live.o $(ROOT_HW_SUPPORT) build/root-native-boot.o
build/root-unsafe.elf: build/boot-root-unsafe.o $(ROOT_HW_SUPPORT) build/root-unsafe-native-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-root-unsafe.o $(ROOT_HW_SUPPORT) build/root-unsafe-native-boot.o
build/root-spoof.elf: build/boot-root-spoof.o $(ROOT_HW_SUPPORT) build/root-native-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-root-spoof.o $(ROOT_HW_SUPPORT) build/root-native-boot.o
build/root-%-multiboot.elf: build/root-%.elf
	objcopy -O elf32-i386 "$<" "$@"
test-cr3-root-hw: build/root-live-multiboot.elf build/root-unsafe-multiboot.elf build/root-spoof-multiboot.elf
	$(PYTHON) tests/test_cr3_root_qemu.py --qemu "$(QEMU)"

# Real HIA page memory zeroing; only a caller-owned exact 4KiB capability.
build/page-zero.o: src/page_zero.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.page-zero.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/page-zero.so: build/page-zero.o
	ld -shared -z noexecstack -o "$@" "$<"

build/page-zero-unsafe.o: tests/negative/page_zero_allow_all.hepta | build check-compiler
	"$(HEPTA_COMPILER)" < "$<" > "$@"

build/page-zero-unsafe.so: build/page-zero-unsafe.o
	ld -shared -z noexecstack -o "$@" "$<"

test-page-zero: build/page-zero.so build/page-zero-unsafe.so
	@set -eu; tmp=$$(mktemp build/.page-zero-identity.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	env -i PATH= "$(HEPTA_COMPILER)" < src/page_zero.hepta > "$$tmp"; \
	cmp "$$tmp" build/page-zero.o
	timeout 90 $(PYTHON) tests/test_page_zero.py build/page-zero.so
	$(PYTHON) tests/test_page_zero.py build/page-zero-unsafe.so --expect-unsafe

# QEMU bare-metal verification of the exact native HIA page-zero object against
# E820-admitted and HIA-PMM-allocated physical pages in two separate zones.
# All privilege, firmware transport, PMM coordination and readback are clearly
# labeled NON-HIA test observer code, not a HIA page-zero ownership proof.
build/page-zero-boot.o: build/page-zero.o
	objcopy --redefine-sym f0=page_zero_f0 "$<" "$@"

build/page-zero-dishonest-boot.o: build/page-zero-unsafe.o
	objcopy --redefine-sym f0=page_zero_f0 "$<" "$@"

build/boot-page-zero-hw.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PAGE_ZERO_HW=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-page-zero-decoy.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PAGE_ZERO_HW=1 -DHEPTAKERNEL_TEST_PAGE_ZERO_DECOY=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

PAGE_ZERO_HW_SUPPORT := build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o

build/page-zero-hw.elf: build/boot-page-zero-hw.o $(PAGE_ZERO_HW_SUPPORT) build/page-zero-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-page-zero-hw.o $(PAGE_ZERO_HW_SUPPORT) build/page-zero-boot.o

build/page-zero-dishonest.elf: build/boot-page-zero-hw.o $(PAGE_ZERO_HW_SUPPORT) build/page-zero-dishonest-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-page-zero-hw.o $(PAGE_ZERO_HW_SUPPORT) build/page-zero-dishonest-boot.o

build/page-zero-decoy.elf: build/boot-page-zero-decoy.o $(PAGE_ZERO_HW_SUPPORT) build/page-zero-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-page-zero-decoy.o $(PAGE_ZERO_HW_SUPPORT) build/page-zero-boot.o

# Deliberate physical-reuse bypass: it forges the HIA reply but leaves
# reallocated real RAM dirty. Independent QEMU RAM readback must reject it.
build/boot-page-zero-recycle-bypass.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PAGE_ZERO_HW=1 -DHEPTAKERNEL_TEST_PAGE_ZERO_RECYCLE_BYPASS=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/page-zero-recycle-bypass.elf: build/boot-page-zero-recycle-bypass.o $(PAGE_ZERO_HW_SUPPORT) build/page-zero-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-page-zero-recycle-bypass.o $(PAGE_ZERO_HW_SUPPORT) build/page-zero-boot.o

build/page-zero-%-multiboot.elf: build/page-zero-%.elf
	objcopy -O elf32-i386 "$<" "$@"

.PHONY: test-page-zero-hw
test-page-zero-hw: build/page-zero-hw-multiboot.elf build/page-zero-dishonest-multiboot.elf build/page-zero-decoy-multiboot.elf build/page-zero-recycle-bypass-multiboot.elf
	@set -eu; original=$$(mktemp build/.page-zero-original.XXXXXX); renamed=$$(mktemp build/.page-zero-renamed.XXXXXX); \
	  trap 'rm -f "$$original" "$$renamed"' EXIT HUP INT TERM; \
	  objcopy --dump-section .text="$$original" build/page-zero.o; \
	  objcopy --dump-section .text="$$renamed" build/page-zero-boot.o; \
	  cmp "$$original" "$$renamed"
	$(PYTHON) tests/test_page_zero_qemu.py --qemu "$(QEMU)"

# Actual native HIA page_copy on two disjoint E820/HIA-PMM-owned cross-zone
# physical page pairs; the explicit NON-HIA QEMU bridge is solely observer.
build/page-copy-boot.o: build/page-copy.o
	objcopy --redefine-sym f0=page_copy_f0 "$<" "$@"

build/page-copy-dishonest-boot.o: build/page-copy-unsafe.o
	objcopy --redefine-sym f0=page_copy_f0 "$<" "$@"

build/boot-page-copy-hw.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PAGE_COPY_HW=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-page-copy-decoy.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PAGE_COPY_HW=1 -DHEPTAKERNEL_TEST_PAGE_COPY_DECOY=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-page-copy-source-decoy.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PAGE_COPY_HW=1 -DHEPTAKERNEL_TEST_PAGE_COPY_SOURCE_DECOY=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

# Inject HIA PMM header identity and free-bitmap/accounting inconsistencies
# before the first HIA page_copy: both independent negative images must fail.
build/boot-page-copy-owner-base-forge.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PAGE_COPY_HW=1 -DHEPTAKERNEL_TEST_PAGE_COPY_OWNER_BASE_FORGE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-page-copy-owner-count-forge.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PAGE_COPY_HW=1 -DHEPTAKERNEL_TEST_PAGE_COPY_OWNER_COUNT_FORGE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

PAGE_COPY_HW_SUPPORT := $(PAGE_ZERO_HW_SUPPORT)

build/page-copy-hw.elf: build/boot-page-copy-hw.o $(PAGE_COPY_HW_SUPPORT) build/page-copy-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-page-copy-hw.o $(PAGE_COPY_HW_SUPPORT) build/page-copy-boot.o

build/page-copy-dishonest.elf: build/boot-page-copy-hw.o $(PAGE_COPY_HW_SUPPORT) build/page-copy-dishonest-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-page-copy-hw.o $(PAGE_COPY_HW_SUPPORT) build/page-copy-dishonest-boot.o

build/page-copy-decoy.elf: build/boot-page-copy-decoy.o $(PAGE_COPY_HW_SUPPORT) build/page-copy-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-page-copy-decoy.o $(PAGE_COPY_HW_SUPPORT) build/page-copy-boot.o

build/page-copy-source-decoy.elf: build/boot-page-copy-source-decoy.o $(PAGE_COPY_HW_SUPPORT) build/page-copy-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-page-copy-source-decoy.o $(PAGE_COPY_HW_SUPPORT) build/page-copy-boot.o

build/page-copy-owner-base-forge.elf: build/boot-page-copy-owner-base-forge.o $(PAGE_COPY_HW_SUPPORT) build/page-copy-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-page-copy-owner-base-forge.o $(PAGE_COPY_HW_SUPPORT) build/page-copy-boot.o

build/page-copy-owner-count-forge.elf: build/boot-page-copy-owner-count-forge.o $(PAGE_COPY_HW_SUPPORT) build/page-copy-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-page-copy-owner-count-forge.o $(PAGE_COPY_HW_SUPPORT) build/page-copy-boot.o

build/page-copy-%-multiboot.elf: build/page-copy-%.elf
	objcopy -O elf32-i386 "$<" "$@"

# Copy-then-detach data path using two *original* HIA native functions:
# first copy each cross-zone physical page, then HIA-zero its destination.
# Dishonest variant substitutes a genuine compiled HIA no-op for the zero.
build/boot-page-copy-detach.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PAGE_COPY_HW=1 -DHEPTAKERNEL_TEST_PAGE_COPY_DETACH=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-page-copy-detach-source-decoy.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PAGE_COPY_HW=1 -DHEPTAKERNEL_TEST_PAGE_COPY_DETACH=1 -DHEPTAKERNEL_TEST_PAGE_COPY_DETACH_SOURCE_DECOY=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/page-copy-detach.elf: build/boot-page-copy-detach.o $(PAGE_COPY_HW_SUPPORT) build/page-copy-boot.o build/page-zero-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-page-copy-detach.o $(PAGE_COPY_HW_SUPPORT) build/page-copy-boot.o build/page-zero-boot.o

build/page-copy-detach-bypass.elf: build/boot-page-copy-detach.o $(PAGE_COPY_HW_SUPPORT) build/page-copy-boot.o build/page-zero-dishonest-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-page-copy-detach.o $(PAGE_COPY_HW_SUPPORT) build/page-copy-boot.o build/page-zero-dishonest-boot.o

build/page-copy-detach-source-decoy.elf: build/boot-page-copy-detach-source-decoy.o $(PAGE_COPY_HW_SUPPORT) build/page-copy-boot.o build/page-zero-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-page-copy-detach-source-decoy.o $(PAGE_COPY_HW_SUPPORT) build/page-copy-boot.o build/page-zero-boot.o

.PHONY: test-page-copy-hw
test-page-copy-hw: build/page-copy-hw-multiboot.elf build/page-copy-dishonest-multiboot.elf build/page-copy-decoy-multiboot.elf build/page-copy-source-decoy-multiboot.elf build/page-copy-owner-base-forge-multiboot.elf build/page-copy-owner-count-forge-multiboot.elf build/page-copy-detach-multiboot.elf build/page-copy-detach-bypass-multiboot.elf build/page-copy-detach-source-decoy-multiboot.elf
	@set -eu; original=$$(mktemp build/.page-copy-original.XXXXXX); renamed=$$(mktemp build/.page-copy-renamed.XXXXXX); \
	  trap 'rm -f "$$original" "$$renamed"' EXIT HUP INT TERM; \
	  objcopy --dump-section .text="$$original" build/page-copy.o; \
	  objcopy --dump-section .text="$$renamed" build/page-copy-boot.o; \
	  cmp "$$original" "$$renamed"; \
	  objcopy --dump-section .text="$$original" build/page-zero.o; \
	  objcopy --dump-section .text="$$renamed" build/page-zero-boot.o; \
	  cmp "$$original" "$$renamed"
	$(PYTHON) tests/test_page_copy_qemu.py --qemu "$(QEMU)"

# Bounded single-owner COW reference-count byte transition, NOT an SMP primitive.
build/cow-refcount.o: src/cow_refcount.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.cow-refcount.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/cow-refcount.so: build/cow-refcount.o
	ld -shared -z noexecstack -o "$@" "$<"

build/cow-refcount-unsafe.o: tests/negative/cow_refcount_noop.hepta | build check-compiler
	"$(HEPTA_COMPILER)" < "$<" > "$@"

build/cow-refcount-unsafe.so: build/cow-refcount-unsafe.o
	ld -shared -z noexecstack -o "$@" "$<"

.PHONY: test-cow-refcount
test-cow-refcount: build/cow-refcount.so build/cow-refcount-unsafe.so
	@set -eu; tmp=$$(mktemp build/.cow-byte-identity.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	env -i PATH= "$(HEPTA_COMPILER)" < src/cow_refcount.hepta > "$$tmp"; \
	cmp "$$tmp" build/cow-refcount.o
	timeout 90 $(PYTHON) tests/test_cow_refcount.py build/cow-refcount.so
	$(PYTHON) tests/test_cow_refcount.py build/cow-refcount-unsafe.so --expect-unsafe


# Isolated PC/Q35 native-HIA refcount transitions in actual QEMU guest RAM.
# The explicitly non-HIA bridge performs the independent byte-level oracle.
build/cow-refcount-boot.o: build/cow-refcount.o
	objcopy --redefine-sym f0=cow_refcount_f0 "$<" "$@"

build/cow-refcount-dishonest-boot.o: build/cow-refcount-unsafe.o
	objcopy --redefine-sym f0=cow_refcount_f0 "$<" "$@"

build/boot-cow-refcount-hw.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_COW_REFCOUNT_HW=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-cow-refcount-stale.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_COW_REFCOUNT_HW=1 -DHEPTAKERNEL_TEST_COW_REFCOUNT_STALE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-cow-refcount-decoy.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_COW_REFCOUNT_HW=1 -DHEPTAKERNEL_TEST_COW_REFCOUNT_DECOY=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

COW_REFCOUNT_HW_SUPPORT := $(PAGE_ZERO_HW_SUPPORT)

build/cow-refcount-hw.elf: build/boot-cow-refcount-hw.o $(COW_REFCOUNT_HW_SUPPORT) build/cow-refcount-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-refcount-hw.o $(COW_REFCOUNT_HW_SUPPORT) build/cow-refcount-boot.o

build/cow-refcount-dishonest.elf: build/boot-cow-refcount-hw.o $(COW_REFCOUNT_HW_SUPPORT) build/cow-refcount-dishonest-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-refcount-hw.o $(COW_REFCOUNT_HW_SUPPORT) build/cow-refcount-dishonest-boot.o

build/cow-refcount-stale.elf: build/boot-cow-refcount-stale.o $(COW_REFCOUNT_HW_SUPPORT) build/cow-refcount-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-refcount-stale.o $(COW_REFCOUNT_HW_SUPPORT) build/cow-refcount-boot.o

build/cow-refcount-decoy.elf: build/boot-cow-refcount-decoy.o $(COW_REFCOUNT_HW_SUPPORT) build/cow-refcount-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-refcount-decoy.o $(COW_REFCOUNT_HW_SUPPORT) build/cow-refcount-boot.o

build/cow-refcount-%-multiboot.elf: build/cow-refcount-%.elf
	objcopy -O elf32-i386 "$<" "$@"

.PHONY: test-cow-refcount-hw
test-cow-refcount-hw: build/cow-refcount-hw-multiboot.elf build/cow-refcount-dishonest-multiboot.elf build/cow-refcount-stale-multiboot.elf build/cow-refcount-decoy-multiboot.elf
	@set -eu; original=$$(mktemp build/.cow-original.XXXXXX); renamed=$$(mktemp build/.cow-boot.XXXXXX); \
	  trap 'rm -f "$$original" "$$renamed"' EXIT HUP INT TERM; \
	  objcopy --dump-section .text="$$original" build/cow-refcount.o; \
	  objcopy --dump-section .text="$$renamed" build/cow-refcount-boot.o; \
	  cmp "$$original" "$$renamed"
	timeout 130 $(PYTHON) tests/test_cow_refcount_qemu.py --qemu "$(QEMU)"



# Genuine HIA Core v8 unpublished COW split abort (page zero + refcount restore).
build/cow-abort.o: src/cow_abort.hepta | build check-compiler
	@set -eu; tmp=$(mktemp build/.cow-abort.XXXXXX); trap 'rm -f "$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$tmp"; test -s "$tmp"; \
	test -z "$(nm -u "$tmp")"; mv "$tmp" "$@"

build/cow-abort.so: build/cow-abort.o
	ld -shared -z noexecstack -o "$@" "$<"

build/cow-abort-unsafe.o: tests/negative/cow_abort_noop.hepta | build check-compiler
	"$(HEPTA_COMPILER)" < "$<" > "$@"

build/cow-abort-unsafe.so: build/cow-abort-unsafe.o
	ld -shared -z noexecstack -o "$@" "$<"

.PHONY: test-cow-abort
test-cow-abort: build/cow-abort.so build/cow-abort-unsafe.so build/cow-split.so
	@set -eu; tmp=$(mktemp build/.cow-abort-identity.XXXXXX); trap 'rm -f "$tmp"' EXIT HUP INT TERM; \
	env -i PATH= "$(HEPTA_COMPILER)" < src/cow_abort.hepta > "$tmp"; cmp "$tmp" build/cow-abort.o
	timeout 90 $(PYTHON) tests/test_cow_abort.py build/cow-abort.so --split-library build/cow-split.so
	$(PYTHON) tests/test_cow_abort.py build/cow-abort-unsafe.so --expect-unsafe

# Genuine HIA Core v8 single-owner shared-page detach+copy (not atomic COW).
build/cow-split.o: src/cow_split.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.cow-split.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/cow-split.so: build/cow-split.o
	ld -shared -z noexecstack -o "$@" "$<"

build/cow-split-unsafe.o: tests/negative/cow_split_noop.hepta | build check-compiler
	"$(HEPTA_COMPILER)" < "$<" > "$@"

build/cow-split-unsafe.so: build/cow-split-unsafe.o
	ld -shared -z noexecstack -o "$@" "$<"

.PHONY: test-cow-split
test-cow-split: build/cow-split.so build/cow-split-unsafe.so
	@set -eu; tmp=$$(mktemp build/.cow-split-identity.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	env -i PATH= "$(HEPTA_COMPILER)" < src/cow_split.hepta > "$$tmp"; \
	cmp "$$tmp" build/cow-split.o
	timeout 90 $(PYTHON) tests/test_cow_split.py build/cow-split.so
	$(PYTHON) tests/test_cow_split.py build/cow-split-unsafe.so --expect-unsafe


# Real HIA native page+count COW split in E820/PMM guest physical RAM.
build/cow-split-boot.o: build/cow-split.o
	objcopy --redefine-sym f0=cow_split_f0 "$<" "$@"

build/cow-split-dishonest-boot.o: build/cow-split-unsafe.o
	objcopy --redefine-sym f0=cow_split_f0 "$<" "$@"

build/boot-cow-split-hw.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_COW_SPLIT_HW=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-cow-split-stale.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_COW_SPLIT_HW=1 -DHEPTAKERNEL_TEST_COW_SPLIT_STALE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-cow-split-dest-decoy.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_COW_SPLIT_HW=1 -DHEPTAKERNEL_TEST_COW_SPLIT_DEST_DECOY=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-cow-split-source-decoy.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_COW_SPLIT_HW=1 -DHEPTAKERNEL_TEST_COW_SPLIT_SOURCE_DECOY=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

COW_SPLIT_HW_SUPPORT := $(PAGE_ZERO_HW_SUPPORT)

build/cow-split-hw.elf: build/boot-cow-split-hw.o $(COW_SPLIT_HW_SUPPORT) build/cow-split-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-split-hw.o $(COW_SPLIT_HW_SUPPORT) build/cow-split-boot.o

build/cow-split-dishonest.elf: build/boot-cow-split-hw.o $(COW_SPLIT_HW_SUPPORT) build/cow-split-dishonest-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-split-hw.o $(COW_SPLIT_HW_SUPPORT) build/cow-split-dishonest-boot.o

build/cow-split-stale.elf: build/boot-cow-split-stale.o $(COW_SPLIT_HW_SUPPORT) build/cow-split-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-split-stale.o $(COW_SPLIT_HW_SUPPORT) build/cow-split-boot.o

build/cow-split-dest-decoy.elf: build/boot-cow-split-dest-decoy.o $(COW_SPLIT_HW_SUPPORT) build/cow-split-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-split-dest-decoy.o $(COW_SPLIT_HW_SUPPORT) build/cow-split-boot.o

build/cow-split-source-decoy.elf: build/boot-cow-split-source-decoy.o $(COW_SPLIT_HW_SUPPORT) build/cow-split-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-split-source-decoy.o $(COW_SPLIT_HW_SUPPORT) build/cow-split-boot.o

build/cow-split-%-multiboot.elf: build/cow-split-%.elf
	objcopy -O elf32-i386 "$<" "$@"

.PHONY: test-cow-split-hw
test-cow-split-hw: build/cow-split-hw-multiboot.elf build/cow-split-dishonest-multiboot.elf build/cow-split-stale-multiboot.elf build/cow-split-dest-decoy-multiboot.elf build/cow-split-source-decoy-multiboot.elf
	@set -eu; original=$$(mktemp build/.split-original.XXXXXX); renamed=$$(mktemp build/.split-boot.XXXXXX); \
	  trap 'rm -f "$$original" "$$renamed"' EXIT HUP INT TERM; \
	  objcopy --dump-section .text="$$original" build/cow-split.o; \
	  objcopy --dump-section .text="$$renamed" build/cow-split-boot.o; \
	  cmp "$$original" "$$renamed"
	timeout 180 $(PYTHON) tests/test_cow_split_qemu.py --qemu "$(QEMU)"

# HIA-native restricted COW private-frame PTE transition, single-owner only.
build/cow-pte-swap.o: src/cow_pte_swap.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.cow-pte-swap.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	env -i PATH= "$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/cow-pte-swap.so: build/cow-pte-swap.o
	ld -shared -z noexecstack -o "$@" "$<"

build/cow-pte-swap-unsafe.o: tests/negative/cow_pte_swap_noop.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.cow-pte-swap-unsafe.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	env -i PATH= "$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/cow-pte-swap-unsafe.so: build/cow-pte-swap-unsafe.o
	ld -shared -z noexecstack -o "$@" "$<"

.PHONY: test-cow-pte-swap
test-cow-pte-swap: build/cow-pte-swap.so build/cow-pte-swap-unsafe.so
	@set -eu; tmp=$$(mktemp build/.cow-pte-swap-byte.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	env -i PATH= "$(HEPTA_COMPILER)" < src/cow_pte_swap.hepta > "$$tmp"; cmp "$$tmp" build/cow-pte-swap.o
	timeout 90 $(PYTHON) tests/test_cow_pte_swap.py build/cow-pte-swap.so
	$(PYTHON) tests/test_cow_pte_swap.py build/cow-pte-swap-unsafe.so --expect-unsafe

# Actual supervisor #PF -> original HIA native COW PTE remap -> non-HIA INVLPG
# -> IRETQ retry of exact store and full physical page-byte oracle.
# The privilege/exception bridge is NEVER classified as HIA.
build/cow-pte-boot.o: build/cow-pte-swap.o
	objcopy --redefine-sym f0=cow_pte_f0 "$<" "$@"

build/cow-pte-dishonest-boot.o: build/cow-pte-swap-unsafe.o
	objcopy --redefine-sym f0=cow_pte_f0 "$<" "$@"

build/boot-cow-pte-hw.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_COW_PTE_HW=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-cow-pte-stale.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_COW_PTE_HW=1 -DHEPTAKERNEL_TEST_COW_PTE_STALE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-cow-pte-bypass.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_COW_PTE_HW=1 -DHEPTAKERNEL_TEST_COW_PTE_BYPASS=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

COW_PTE_HW_SUPPORT := $(PAGE_ZERO_HW_SUPPORT)

build/cow-pte-hw.elf: build/boot-cow-pte-hw.o $(COW_PTE_HW_SUPPORT) build/cow-pte-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-pte-hw.o $(COW_PTE_HW_SUPPORT) build/cow-pte-boot.o

build/cow-pte-stale.elf: build/boot-cow-pte-stale.o $(COW_PTE_HW_SUPPORT) build/cow-pte-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-pte-stale.o $(COW_PTE_HW_SUPPORT) build/cow-pte-boot.o

build/cow-pte-bypass.elf: build/boot-cow-pte-bypass.o $(COW_PTE_HW_SUPPORT) build/cow-pte-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-pte-bypass.o $(COW_PTE_HW_SUPPORT) build/cow-pte-boot.o

build/cow-pte-dishonest.elf: build/boot-cow-pte-hw.o $(COW_PTE_HW_SUPPORT) build/cow-pte-dishonest-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-pte-hw.o $(COW_PTE_HW_SUPPORT) build/cow-pte-dishonest-boot.o

build/cow-pte-%-multiboot.elf: build/cow-pte-%.elf
	objcopy -O elf32-i386 "$<" "$@"

.PHONY: test-cow-pte-hw
test-cow-pte-hw: build/cow-pte-hw-multiboot.elf build/cow-pte-stale-multiboot.elf build/cow-pte-bypass-multiboot.elf build/cow-pte-dishonest-multiboot.elf
	@set -eu; orig=$$(mktemp build/.cow-pte-original.XXXXXX); boot=$$(mktemp build/.cow-pte-boot.XXXXXX); \
	  trap 'rm -f "$$orig" "$$boot"' EXIT HUP INT TERM; \
	  objcopy --dump-section .text="$$orig" build/cow-pte-swap.o; \
	  objcopy --dump-section .text="$$boot" build/cow-pte-boot.o; \
	  cmp "$$orig" "$$boot"
	timeout 160 $(PYTHON) tests/test_cow_pte_swap_qemu.py --qemu "$(QEMU)"

# One actual QEMU #PF: unmodified HIA cow_split clones full 4KiB plus counts,
# then unmodified HIA cow_pte_swap replaces the live PTE. Privilege/IRET is
# explicitly the non-HIA assembly oracle, not a HIA kernel implementation.
.PHONY: test-cow-integrated-hw
build/boot-cow-integrated-hw.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_COW_PTE_HW=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-cow-integrated-stale.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_COW_PTE_HW=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED_STALE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-cow-integrated-decoy.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_COW_PTE_HW=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED_DECOY=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

COW_INTEGRATED_SUPPORT := $(COW_PTE_HW_SUPPORT) build/cow-pte-boot.o

build/cow-integrated-hw.elf: build/boot-cow-integrated-hw.o $(COW_INTEGRATED_SUPPORT) build/cow-split-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-integrated-hw.o $(COW_INTEGRATED_SUPPORT) build/cow-split-boot.o

build/cow-integrated-stale.elf: build/boot-cow-integrated-stale.o $(COW_INTEGRATED_SUPPORT) build/cow-split-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-integrated-stale.o $(COW_INTEGRATED_SUPPORT) build/cow-split-boot.o

build/cow-integrated-dishonest.elf: build/boot-cow-integrated-hw.o $(COW_INTEGRATED_SUPPORT) build/cow-split-dishonest-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-integrated-hw.o $(COW_INTEGRATED_SUPPORT) build/cow-split-dishonest-boot.o

build/cow-integrated-decoy.elf: build/boot-cow-integrated-decoy.o $(COW_INTEGRATED_SUPPORT) build/cow-split-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-integrated-decoy.o $(COW_INTEGRATED_SUPPORT) build/cow-split-boot.o

build/cow-abort-boot.o: build/cow-abort.o
	objcopy --redefine-sym f0=cow_abort_f0 "$<" "$@"

build/cow-abort-dishonest-boot.o: build/cow-abort-unsafe.o
	objcopy --redefine-sym f0=cow_abort_f0 "$<" "$@"

build/boot-cow-integrated-abort.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_COW_PTE_HW=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED_ABORT=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/cow-integrated-abort.elf: build/boot-cow-integrated-abort.o $(COW_INTEGRATED_SUPPORT) build/cow-split-boot.o build/cow-abort-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-integrated-abort.o $(COW_INTEGRATED_SUPPORT) build/cow-split-boot.o build/cow-abort-boot.o

build/cow-integrated-abort-noop.elf: build/boot-cow-integrated-abort.o $(COW_INTEGRATED_SUPPORT) build/cow-split-boot.o build/cow-abort-dishonest-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-integrated-abort.o $(COW_INTEGRATED_SUPPORT) build/cow-split-boot.o build/cow-abort-dishonest-boot.o

# A genuine HIA PTE-guarded abort reads eight bytes from the live QEMU
# page-table leaf, independently observing late publication and stale header.
build/cow-abort-pte-guarded-boot.o: build/cow-abort-pte-guarded.o
	objcopy --redefine-sym f0=cow_abort_pte_guarded_f0 "$<" "$@"

build/cow-abort-pte-guarded-dishonest-boot.o: build/cow-abort-pte-guarded-noop.o
	objcopy --redefine-sym f0=cow_abort_pte_guarded_f0 "$<" "$@"

build/boot-cow-integrated-guarded.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_COW_PTE_HW=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED_ABORT=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED_ABORT_GUARDED=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-cow-integrated-guarded-stale.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_COW_PTE_HW=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED_ABORT=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED_ABORT_GUARDED=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED_GUARD_STALE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-cow-integrated-guarded-published.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_COW_PTE_HW=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED_ABORT=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED_ABORT_GUARDED=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED_GUARD_PUBLISHED=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

COW_GUARDED_SUPPORT := $(COW_INTEGRATED_SUPPORT) build/cow-split-boot.o build/cow-abort-pte-guarded-boot.o

build/cow-integrated-guarded.elf: build/boot-cow-integrated-guarded.o $(COW_GUARDED_SUPPORT) arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-integrated-guarded.o $(COW_GUARDED_SUPPORT)

build/cow-integrated-guarded-stale.elf: build/boot-cow-integrated-guarded-stale.o $(COW_GUARDED_SUPPORT) arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-integrated-guarded-stale.o $(COW_GUARDED_SUPPORT)

build/cow-integrated-guarded-published.elf: build/boot-cow-integrated-guarded-published.o $(COW_GUARDED_SUPPORT) arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-integrated-guarded-published.o $(COW_GUARDED_SUPPORT)

build/cow-integrated-guarded-noop.elf: build/boot-cow-integrated-guarded.o $(COW_INTEGRATED_SUPPORT) build/cow-split-boot.o build/cow-abort-pte-guarded-dishonest-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-integrated-guarded.o $(COW_INTEGRATED_SUPPORT) build/cow-split-boot.o build/cow-abort-pte-guarded-dishonest-boot.o


# Native HIA PMM release/reissue after genuine HIA live-PTE-guarded abort.
COW_RECYCLE_FLAGS := -DHEPTAKERNEL_TEST_COW_PTE_HW=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED=1 -DHEPTAKERNEL_TEST_COW_FRAME_BINDING_HW=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED_ABORT=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED_ABORT_GUARDED=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED_RECYCLE=1
COW_RECYCLE_SUPPORT := $(COW_GUARDED_SUPPORT) build/cow-frame-binding-boot.o

build/boot-cow-integrated-recycle.o: arch/x86_64/boot.S build/boot-cases.bin
	cc $(COW_RECYCLE_FLAGS) -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-cow-integrated-recycle-double.o: arch/x86_64/boot.S build/boot-cases.bin
	cc $(COW_RECYCLE_FLAGS) -DHEPTAKERNEL_TEST_COW_INTEGRATED_RECYCLE_DOUBLE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/cow-integrated-recycle.elf: build/boot-cow-integrated-recycle.o $(COW_RECYCLE_SUPPORT) arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-integrated-recycle.o $(COW_RECYCLE_SUPPORT)

build/cow-integrated-recycle-double.elf: build/boot-cow-integrated-recycle-double.o $(COW_RECYCLE_SUPPORT) arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-integrated-recycle-double.o $(COW_RECYCLE_SUPPORT)

build/cow-integrated-%-multiboot.elf: build/cow-integrated-%.elf
	objcopy -O elf32-i386 "$<" "$@"

test-cow-integrated-hw: build/cow-integrated-hw-multiboot.elf build/cow-integrated-stale-multiboot.elf build/cow-integrated-dishonest-multiboot.elf build/cow-integrated-decoy-multiboot.elf build/cow-integrated-abort-multiboot.elf build/cow-integrated-abort-noop-multiboot.elf build/cow-integrated-guarded-multiboot.elf build/cow-integrated-guarded-noop-multiboot.elf build/cow-integrated-guarded-stale-multiboot.elf build/cow-integrated-guarded-published-multiboot.elf build/cow-integrated-recycle-multiboot.elf build/cow-integrated-recycle-double-multiboot.elf
	@set -eu; a=$$(mktemp build/.cow-integrated-split-a.XXXXXX); b=$$(mktemp build/.cow-integrated-split-b.XXXXXX); c=$$(mktemp build/.cow-integrated-pte-a.XXXXXX); d=$$(mktemp build/.cow-integrated-pte-b.XXXXXX); \
	  trap 'rm -f "$$a" "$$b" "$$c" "$$d"' EXIT HUP INT TERM; \
	  objcopy --dump-section .text="$$a" build/cow-split.o; objcopy --dump-section .text="$$b" build/cow-split-boot.o; cmp "$$a" "$$b"; \
	  objcopy --dump-section .text="$$c" build/cow-pte-swap.o; objcopy --dump-section .text="$$d" build/cow-pte-boot.o; cmp "$$c" "$$d"; \
	  objcopy --dump-section .text="$$a" build/cow-abort.o; objcopy --dump-section .text="$$b" build/cow-abort-boot.o; cmp "$$a" "$$b"; \
	  objcopy --dump-section .text="$$a" build/cow-abort-pte-guarded.o; objcopy --dump-section .text="$$b" build/cow-abort-pte-guarded-boot.o; cmp "$$a" "$$b"
	timeout 240 $(PYTHON) tests/test_cow_integrated_qemu.py --qemu "$(QEMU)"

# Native Core v8 PTE-guarded prepublication COW cleanup (single-owner).
# The trusted caller must supply the actual live PTE as the eight-byte readbuf.
build/cow-abort-pte-guarded.o: src/cow_abort_pte_guarded.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.cow-abort-pte-guarded.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/cow-abort-pte-guarded.so: build/cow-abort-pte-guarded.o
	ld -shared -z noexecstack -o "$@" "$<"

build/cow-abort-pte-guarded-noop.o: tests/negative/cow_abort_pte_guarded_noop.hepta | build check-compiler
	"$(HEPTA_COMPILER)" < "$<" > "$@"

build/cow-abort-pte-guarded-noop.so: build/cow-abort-pte-guarded-noop.o
	ld -shared -z noexecstack -o "$@" "$<"

.PHONY: test-cow-abort-pte-guarded
test-cow-abort-pte-guarded: build/cow-abort-pte-guarded.so build/cow-abort-pte-guarded-noop.so build/cow-split.so
	@set -eu; tmp=$$(mktemp build/.cow-abort-pte-guarded-identity.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	env -i PATH= "$(HEPTA_COMPILER)" < src/cow_abort_pte_guarded.hepta > "$$tmp"; cmp "$$tmp" build/cow-abort-pte-guarded.o
	timeout 90 $(PYTHON) tests/test_cow_abort_pte_guarded.py build/cow-abort-pte-guarded.so --split-library build/cow-split.so
	$(PYTHON) tests/test_cow_abort_pte_guarded.py build/cow-abort-pte-guarded-noop.so --expect-unsafe

# Read-only native HIA admission binds the live COW PTE to two allocated
# frames of one actual HIA PMM arena; no non-HIA COW implementation.
.PHONY: test-cow-frame-binding
build/cow-frame-binding.o: src/cow_frame_binding.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.cow-frame-binding.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	env -i PATH= "$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/cow-frame-binding.so: build/cow-frame-binding.o
	ld -shared -z noexecstack -o "$@" "$<"

build/cow-frame-binding-noop.o: tests/negative/cow_frame_binding_noop.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.cow-frame-binding-noop.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	env -i PATH= "$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/cow-frame-binding-noop.so: build/cow-frame-binding-noop.o
	ld -shared -z noexecstack -o "$@" "$<"

test-cow-frame-binding: build/cow-frame-binding.so build/cow-frame-binding-noop.so
	@set -eu; tmp=$$(mktemp build/.cow-frame-binding-byte.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	env -i PATH= "$(HEPTA_COMPILER)" < src/cow_frame_binding.hepta > "$$tmp"; cmp "$$tmp" build/cow-frame-binding.o
	timeout 90 $(PYTHON) tests/test_cow_frame_binding.py build/cow-frame-binding.so
	$(PYTHON) tests/test_cow_frame_binding.py build/cow-frame-binding-noop.so --expect-unsafe

# Quiescent QEMU integration: native HIA PMM allocation, actual live PTE,
# native read-only HIA frame-binding gate, then hardware #PF/COW remap.
# All privileged setup/exception instructions remain NON-HIA boot bridge.
.PHONY: test-cow-frame-binding-hw
build/cow-frame-binding-boot.o: build/cow-frame-binding.o
	objcopy --redefine-sym f0=cow_frame_binding_f0 "$<" "$@"

build/cow-frame-binding-dishonest-boot.o: build/cow-frame-binding-noop.o
	objcopy --redefine-sym f0=cow_frame_binding_f0 "$<" "$@"

build/boot-cow-binding-hw.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_COW_PTE_HW=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED=1 -DHEPTAKERNEL_TEST_COW_FRAME_BINDING_HW=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-cow-binding-pte-stale.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_COW_PTE_HW=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED=1 -DHEPTAKERNEL_TEST_COW_FRAME_BINDING_HW=1 -DHEPTAKERNEL_TEST_COW_FRAME_BINDING_PTE_STALE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-cow-binding-bitmap.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_COW_PTE_HW=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED=1 -DHEPTAKERNEL_TEST_COW_FRAME_BINDING_HW=1 -DHEPTAKERNEL_TEST_COW_FRAME_BINDING_BITMAP=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-cow-binding-noop.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_COW_PTE_HW=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED=1 -DHEPTAKERNEL_TEST_COW_FRAME_BINDING_HW=1 -DHEPTAKERNEL_TEST_COW_FRAME_BINDING_BITMAP=1 -DHEPTAKERNEL_TEST_COW_FRAME_BINDING_NOOP=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

COW_BINDING_HW_SUPPORT := $(COW_INTEGRATED_SUPPORT) build/cow-split-boot.o

build/cow-binding-hw.elf: build/boot-cow-binding-hw.o $(COW_BINDING_HW_SUPPORT) build/cow-frame-binding-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-binding-hw.o $(COW_BINDING_HW_SUPPORT) build/cow-frame-binding-boot.o

build/cow-binding-pte-stale.elf: build/boot-cow-binding-pte-stale.o $(COW_BINDING_HW_SUPPORT) build/cow-frame-binding-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-binding-pte-stale.o $(COW_BINDING_HW_SUPPORT) build/cow-frame-binding-boot.o

build/cow-binding-bitmap.elf: build/boot-cow-binding-bitmap.o $(COW_BINDING_HW_SUPPORT) build/cow-frame-binding-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-binding-bitmap.o $(COW_BINDING_HW_SUPPORT) build/cow-frame-binding-boot.o

build/cow-binding-noop.elf: build/boot-cow-binding-noop.o $(COW_BINDING_HW_SUPPORT) build/cow-frame-binding-dishonest-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-cow-binding-noop.o $(COW_BINDING_HW_SUPPORT) build/cow-frame-binding-dishonest-boot.o

build/cow-binding-%-multiboot.elf: build/cow-binding-%.elf
	objcopy -O elf32-i386 "$<" "$@"

test-cow-frame-binding-hw: build/cow-binding-hw-multiboot.elf build/cow-binding-pte-stale-multiboot.elf build/cow-binding-bitmap-multiboot.elf build/cow-binding-noop-multiboot.elf
	@set -eu; a=$$(mktemp build/.cow-binding-hia-source.XXXXXX); b=$$(mktemp build/.cow-binding-hia-linked.XXXXXX); \
	  trap 'rm -f "$$a" "$$b"' EXIT HUP INT TERM; \
	  objcopy --dump-section .text="$$a" build/cow-frame-binding.o; objcopy --dump-section .text="$$b" build/cow-frame-binding-boot.o; cmp "$$a" "$$b"; \
	  objcopy --dump-section .text="$$a" build/cow-frame-binding-noop.o; objcopy --dump-section .text="$$b" build/cow-frame-binding-dishonest-boot.o; cmp "$$a" "$$b"
	timeout 180 $(PYTHON) tests/test_cow_frame_binding_qemu.py --qemu "$(QEMU)"

# Genuine native HIA complete PMM bitmap scan; not an atomic/privileged COW path.
build/pmm-bitmap-integrity.o: src/pmm_bitmap_integrity.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.pmm-bitmap.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/pmm-bitmap-integrity.so: build/pmm-bitmap-integrity.o
	ld -shared -z noexecstack -o "$@" "$<"

build/pmm-bitmap-unsafe.o: tests/negative/pmm_bitmap_noop.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.pmm-bitmap-unsafe.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/pmm-bitmap-unsafe.so: build/pmm-bitmap-unsafe.o
	ld -shared -z noexecstack -o "$@" "$<"

.PHONY: test-pmm-bitmap-integrity
test-pmm-bitmap-integrity: build/pmm-bitmap-integrity.so build/pmm-bitmap-unsafe.so
	timeout 90 $(PYTHON) tests/test_pmm_bitmap_integrity.py build/pmm-bitmap-integrity.so > build/pmm-bitmap-report.json
	$(PYTHON) tests/test_pmm_bitmap_integrity.py build/pmm-bitmap-unsafe.so --expect-unsafe
	@set -eu; compiler=$$(command -v "$(HEPTA_COMPILER)"); \
	one=$$(mktemp build/.pmm-bitmap-repro1.XXXXXX); two=$$(mktemp build/.pmm-bitmap-repro2.XXXXXX); \
	trap 'rm -f "$$one" "$$two"' EXIT HUP INT TERM; \
	env -i PATH='' "$$compiler" < src/pmm_bitmap_integrity.hepta > "$$one"; \
	env -i PATH='' "$$compiler" < src/pmm_bitmap_integrity.hepta > "$$two"; \
	cmp build/pmm-bitmap-integrity.o "$$one"; cmp "$$one" "$$two"


# Real HIA PMM integrity scan gates the QEMU hardware COW path.
# The x86 privileged setup, exception return and observer remain NON-HIA.
.PHONY: test-pmm-bitmap-hw
build/pmm-bitmap-boot.o: build/pmm-bitmap-integrity.o
	objcopy --redefine-sym f0=pmm_bitmap_integrity_f0 "$<" "$@"

build/pmm-bitmap-dishonest-boot.o: build/pmm-bitmap-unsafe.o
	objcopy --redefine-sym f0=pmm_bitmap_integrity_f0 "$<" "$@"

PMM_BITMAP_HW_FLAGS := -DHEPTAKERNEL_TEST_COW_PTE_HW=1 -DHEPTAKERNEL_TEST_COW_INTEGRATED=1 -DHEPTAKERNEL_TEST_COW_FRAME_BINDING_HW=1 -DHEPTAKERNEL_TEST_PMM_BITMAP_COW_HW=1
build/boot-pmm-bitmap-hw.o: arch/x86_64/boot.S build/boot-cases.bin
	cc $(PMM_BITMAP_HW_FLAGS) -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-pmm-bitmap-free-stale.o: arch/x86_64/boot.S build/boot-cases.bin
	cc $(PMM_BITMAP_HW_FLAGS) -DHEPTAKERNEL_TEST_PMM_BITMAP_FREE_STALE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-pmm-bitmap-reserved-missing.o: arch/x86_64/boot.S build/boot-cases.bin
	cc $(PMM_BITMAP_HW_FLAGS) -DHEPTAKERNEL_TEST_PMM_BITMAP_RESERVED_MISSING=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-pmm-bitmap-tail-dirty.o: arch/x86_64/boot.S build/boot-cases.bin
	cc $(PMM_BITMAP_HW_FLAGS) -DHEPTAKERNEL_TEST_PMM_BITMAP_TAIL_DIRTY=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/boot-pmm-bitmap-noop.o: arch/x86_64/boot.S build/boot-cases.bin
	cc $(PMM_BITMAP_HW_FLAGS) -DHEPTAKERNEL_TEST_PMM_BITMAP_FREE_STALE=1 -DHEPTAKERNEL_TEST_PMM_BITMAP_NOOP=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

PMM_BITMAP_HW_SUPPORT := $(COW_BINDING_HW_SUPPORT) build/cow-frame-binding-boot.o
build/pmm-bitmap-hw.elf: build/boot-pmm-bitmap-hw.o $(PMM_BITMAP_HW_SUPPORT) build/pmm-bitmap-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-pmm-bitmap-hw.o $(PMM_BITMAP_HW_SUPPORT) build/pmm-bitmap-boot.o

build/pmm-bitmap-free-stale.elf: build/boot-pmm-bitmap-free-stale.o $(PMM_BITMAP_HW_SUPPORT) build/pmm-bitmap-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-pmm-bitmap-free-stale.o $(PMM_BITMAP_HW_SUPPORT) build/pmm-bitmap-boot.o

build/pmm-bitmap-reserved-missing.elf: build/boot-pmm-bitmap-reserved-missing.o $(PMM_BITMAP_HW_SUPPORT) build/pmm-bitmap-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-pmm-bitmap-reserved-missing.o $(PMM_BITMAP_HW_SUPPORT) build/pmm-bitmap-boot.o

build/pmm-bitmap-tail-dirty.elf: build/boot-pmm-bitmap-tail-dirty.o $(PMM_BITMAP_HW_SUPPORT) build/pmm-bitmap-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-pmm-bitmap-tail-dirty.o $(PMM_BITMAP_HW_SUPPORT) build/pmm-bitmap-boot.o

build/pmm-bitmap-noop.elf: build/boot-pmm-bitmap-noop.o $(PMM_BITMAP_HW_SUPPORT) build/pmm-bitmap-dishonest-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-pmm-bitmap-noop.o $(PMM_BITMAP_HW_SUPPORT) build/pmm-bitmap-dishonest-boot.o

build/pmm-bitmap-%-multiboot.elf: build/pmm-bitmap-%.elf
	objcopy -O elf32-i386 "$<" "$@"

test-pmm-bitmap-hw: build/pmm-bitmap-hw-multiboot.elf build/pmm-bitmap-free-stale-multiboot.elf build/pmm-bitmap-reserved-missing-multiboot.elf build/pmm-bitmap-tail-dirty-multiboot.elf build/pmm-bitmap-noop-multiboot.elf
	@set -eu; a=$$(mktemp build/.pmm-bitmap-qemu-a.XXXXXX); b=$$(mktemp build/.pmm-bitmap-qemu-b.XXXXXX); \
	  trap 'rm -f "$$a" "$$b"' EXIT HUP INT TERM; \
	  objcopy --dump-section .text="$$a" build/pmm-bitmap-integrity.o; objcopy --dump-section .text="$$b" build/pmm-bitmap-boot.o; cmp "$$a" "$$b"; \
	  objcopy --dump-section .text="$$a" build/pmm-bitmap-unsafe.o; objcopy --dump-section .text="$$b" build/pmm-bitmap-dishonest-boot.o; cmp "$$a" "$$b"
	timeout 180 $(PYTHON) tests/test_pmm_bitmap_qemu.py --qemu "$(QEMU)"

# Actual pinned HIA Core v8 native ELF64 x86-64 executable-header admission.
# This is only a byte-level, caller-supplied image gate, not execve/ELF loading.
.PHONY: test-elf64-exec-admit

build/elf64-exec-admit.o: src/elf64_exec_admit.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.elf64-native.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/elf64-exec-admit.so: build/elf64-exec-admit.o
	ld -shared -z noexecstack -o "$@" "$<"

build/elf64-exec-unsafe.o: tests/negative/elf64_exec_allow_all.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.elf64-unsafe.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/elf64-exec-unsafe.so: build/elf64-exec-unsafe.o
	ld -shared -z noexecstack -o "$@" "$<"

test-elf64-exec-admit: build/elf64-exec-admit.so build/elf64-exec-unsafe.so
	timeout 90 $(PYTHON) tests/test_elf64_exec_admit.py build/elf64-exec-admit.so --object build/elf64-exec-admit.o
	$(PYTHON) tests/test_elf64_exec_admit.py build/elf64-exec-unsafe.so --expect-unsafe
	@set -eu; compiler=$$(command -v "$(HEPTA_COMPILER)"); \
	a=$$(mktemp build/.elf64-repro1.XXXXXX); b=$$(mktemp build/.elf64-repro2.XXXXXX); \
	trap 'rm -f "$$a" "$$b"' EXIT HUP INT TERM; \
	env -i PATH='' "$$compiler" < src/elf64_exec_admit.hepta > "$$a"; \
	env -i PATH='' "$$compiler" < src/elf64_exec_admit.hepta > "$$b"; \
	cmp build/elf64-exec-admit.o "$$a"; cmp "$$a" "$$b"

# Genuine native HIA Core v8 ELF64 PT_LOAD file and virtual-span checks.
# This is a restricted, standalone admission component, not an ELF loader.
.PHONY: test-elf64-load-segments

# Compile under the same empty-PATH contract as the independent two-pass
# reproduction below. This object is used by both host native and live QEMU.
build/elf64-load-segments.o: src/elf64_load_segments.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.elf64-load-native.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	compiler=$$(command -v "$(HEPTA_COMPILER)"); \
	env -i PATH='' "$$compiler" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/elf64-load-segments.so: build/elf64-load-segments.o
	ld -shared -z noexecstack -o "$@" "$<"

build/elf64-load-unsafe.o: tests/negative/elf64_load_allow_all.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.elf64-load-unsafe.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/elf64-load-unsafe.so: build/elf64-load-unsafe.o
	ld -shared -z noexecstack -o "$@" "$<"

test-elf64-load-segments: build/elf64-load-segments.so build/elf64-load-unsafe.so
	timeout 90 $(PYTHON) tests/test_elf64_load_segments.py build/elf64-load-segments.so --object build/elf64-load-segments.o
	$(PYTHON) tests/test_elf64_load_segments.py build/elf64-load-unsafe.so --expect-unsafe
	@set -eu; compiler=$$(command -v "$(HEPTA_COMPILER)"); \
	a=$$(mktemp build/.elf64-load-repro1.XXXXXX); b=$$(mktemp build/.elf64-load-repro2.XXXXXX); \
	trap 'rm -f "$$a" "$$b"' EXIT HUP INT TERM; \
	env -i PATH='' "$$compiler" < src/elf64_load_segments.hepta > "$$a"; \
	env -i PATH='' "$$compiler" < src/elf64_load_segments.hepta > "$$b"; \
	cmp build/elf64-load-segments.o "$$a"; cmp "$$a" "$$b"

# Genuine native HIA selected PT_LOAD to page-fill plan, no trusted caller fields.
.PHONY: test-elf64-page-plan

build/elf64-page-plan.o: src/elf64_page_plan.hepta | build check-compiler
	@set -eu; tmp=$(mktemp build/.elf64-plan-native.XXXXXX); trap 'rm -f "$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$tmp"; test -s "$tmp"; \
	test -z "$(nm -u "$tmp")"; mv "$tmp" "$@"

build/elf64-page-plan.so: build/elf64-page-plan.o
	ld -shared -z noexecstack -o "$@" "$<"

build/elf64-page-plan-unsafe.o: tests/negative/elf64_page_plan_noop.hepta | build check-compiler
	@set -eu; tmp=$(mktemp build/.elf64-plan-unsafe.XXXXXX); trap 'rm -f "$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$tmp"; test -s "$tmp"; \
	test -z "$(nm -u "$tmp")"; mv "$tmp" "$@"

build/elf64-page-plan-unsafe.so: build/elf64-page-plan-unsafe.o
	ld -shared -z noexecstack -o "$@" "$<"

test-elf64-page-plan: build/elf64-page-plan.so build/elf64-page-plan-unsafe.so build/elf64-page-fill.so
	timeout 90 $(PYTHON) tests/test_elf64_page_plan.py build/elf64-page-plan.so --object build/elf64-page-plan.o --fill build/elf64-page-fill.so
	$(PYTHON) tests/test_elf64_page_plan.py build/elf64-page-plan-unsafe.so --expect-unsafe
	env -i PATH='' "$(HEPTA_COMPILER)" < src/elf64_page_plan.hepta > build/elf64-page-plan-repro-a.o
	env -i PATH='' "$(HEPTA_COMPILER)" < src/elf64_page_plan.hepta > build/elf64-page-plan-repro-b.o
	cmp build/elf64-page-plan.o build/elf64-page-plan-repro-a.o
	cmp build/elf64-page-plan-repro-a.o build/elf64-page-plan-repro-b.o

# Native HIA ELF64 per-page segment bytes and BSS zeroing. A test component,
# not a general loader or an authorized page-table operation.
.PHONY: test-elf64-page-fill

build/elf64-page-fill.o: src/elf64_page_fill.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.elf64-page-fill.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/elf64-page-fill.so: build/elf64-page-fill.o
	ld -shared -z noexecstack -o "$@" "$<"

build/elf64-page-fill-unsafe.o: tests/negative/elf64_page_fill_noop.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.elf64-page-unsafe.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/elf64-page-fill-unsafe.so: build/elf64-page-fill-unsafe.o
	ld -shared -z noexecstack -o "$@" "$<"

test-elf64-page-fill: build/elf64-page-fill.so build/elf64-page-fill-unsafe.so
	timeout 90 $(PYTHON) tests/test_elf64_page_fill.py build/elf64-page-fill.so --object build/elf64-page-fill.o
	$(PYTHON) tests/test_elf64_page_fill.py build/elf64-page-fill-unsafe.so --expect-unsafe
	@set -eu; compiler=$$(command -v "$(HEPTA_COMPILER)"); \
	a=$$(mktemp build/.elf64-page-repro1.XXXXXX); b=$$(mktemp build/.elf64-page-repro2.XXXXXX); \
	trap 'rm -f "$$a" "$$b"' EXIT HUP INT TERM; \
	env -i PATH='' "$$compiler" < src/elf64_page_fill.hepta > "$$a"; \
	env -i PATH='' "$$compiler" < src/elf64_page_fill.hepta > "$$b"; \
	cmp build/elf64-page-fill.o "$$a"; cmp "$$a" "$$b"

# Isolated QEMU physical-frame ELF file/BSS materialization, original HIA .text.
# Privileged bootstrap, PMM coordination, source fixture and oracle are NON-HIA.
.PHONY: test-elf64-page-hw
build/elf64-page-fill-boot.o: build/elf64-page-fill.o
	objcopy --redefine-sym f0=elf_page_f0 "$<" "$@"
build/elf64-page-fill-dishonest-boot.o: build/elf64-page-fill-unsafe.o
	objcopy --redefine-sym f0=elf_page_f0 "$<" "$@"

build/boot-elf-page-hw.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_ELF_PAGE_HW=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-elf-page-truncated.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_ELF_PAGE_HW=1 -DHEPTAKERNEL_TEST_ELF_PAGE_TRUNCATED=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-elf-page-noop.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_ELF_PAGE_HW=1 -DHEPTAKERNEL_TEST_ELF_PAGE_NOOP=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-elf-page-decoy.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_ELF_PAGE_HW=1 -DHEPTAKERNEL_TEST_ELF_PAGE_DECOY=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

ELF_PAGE_HW_SUPPORT := $(PAGE_ZERO_HW_SUPPORT)
build/elf-page-hw.elf: build/boot-elf-page-hw.o $(ELF_PAGE_HW_SUPPORT) build/elf64-page-fill-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-elf-page-hw.o $(ELF_PAGE_HW_SUPPORT) build/elf64-page-fill-boot.o
build/elf-page-truncated.elf: build/boot-elf-page-truncated.o $(ELF_PAGE_HW_SUPPORT) build/elf64-page-fill-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-elf-page-truncated.o $(ELF_PAGE_HW_SUPPORT) build/elf64-page-fill-boot.o
build/elf-page-noop.elf: build/boot-elf-page-noop.o $(ELF_PAGE_HW_SUPPORT) build/elf64-page-fill-dishonest-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-elf-page-noop.o $(ELF_PAGE_HW_SUPPORT) build/elf64-page-fill-dishonest-boot.o
build/elf-page-decoy.elf: build/boot-elf-page-decoy.o $(ELF_PAGE_HW_SUPPORT) build/elf64-page-fill-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-elf-page-decoy.o $(ELF_PAGE_HW_SUPPORT) build/elf64-page-fill-boot.o
build/elf-page-%-multiboot.elf: build/elf-page-%.elf
	objcopy -O elf32-i386 "$<" "$@"

test-elf64-page-hw: build/elf-page-hw-multiboot.elf build/elf-page-truncated-multiboot.elf build/elf-page-noop-multiboot.elf build/elf-page-decoy-multiboot.elf
	@set -eu; a=$$(mktemp build/.elf-page-original.XXXXXX); b=$$(mktemp build/.elf-page-native.XXXXXX); \
	  trap 'rm -f "$$a" "$$b"' EXIT HUP INT TERM; \
	  objcopy --dump-section .text="$$a" build/elf64-page-fill.o; \
	  objcopy --dump-section .text="$$b" build/elf64-page-fill-boot.o; cmp "$$a" "$$b"; \
	  objcopy --dump-section .text="$$a" build/elf64-page-fill-unsafe.o; \
	  objcopy --dump-section .text="$$b" build/elf64-page-fill-dishonest-boot.o; cmp "$$a" "$$b"
	timeout 160 $(PYTHON) tests/test_elf64_page_fill_qemu.py --qemu "$(QEMU)"


# Native HIA bounded exact-byte snapshot equality; reference provenance is external.
.PHONY: test-elf64-snapshot
build/elf64-snapshot.o: src/elf64_snapshot_equal.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.elf-snapshot.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	compiler=$$(command -v "$(HEPTA_COMPILER)"); \
	env -i PATH='' "$$compiler" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/elf64-snapshot.so: build/elf64-snapshot.o
	ld -shared -z noexecstack -o "$@" "$<"

build/elf64-snapshot-unsafe.o: tests/negative/elf64_snapshot_always_equal.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.elf-snapshot-unsafe.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/elf64-snapshot-unsafe.so: build/elf64-snapshot-unsafe.o
	ld -shared -z noexecstack -o "$@" "$<"

test-elf64-snapshot: build/elf64-snapshot.so build/elf64-snapshot-unsafe.so
	timeout 90 $(PYTHON) tests/test_elf64_snapshot_equal.py build/elf64-snapshot.so --object build/elf64-snapshot.o
	$(PYTHON) tests/test_elf64_snapshot_equal.py build/elf64-snapshot-unsafe.so --expect-unsafe
	@set -eu; a=$$(mktemp build/.snapshot-repro-a.XXXXXX); b=$$(mktemp build/.snapshot-repro-b.XXXXXX); \
	trap 'rm -f "$$a" "$$b"' EXIT HUP INT TERM; \
	env -i PATH='' "$(HEPTA_COMPILER)" < src/elf64_snapshot_equal.hepta > "$$a"; \
	env -i PATH='' "$(HEPTA_COMPILER)" < src/elf64_snapshot_equal.hepta > "$$b"; \
	cmp build/elf64-snapshot.o "$$a"; cmp "$$a" "$$b"

# The unchanged, genuine native HIA page-plan .text is linked into the
# isolated E820/PMM QEMU observer and coupled to the genuine HIA page filler.
# Non-HIA boot.S remains a test fixture, never a HIA privilege backend.
.PHONY: test-elf64-page-plan-hw
build/elf64-page-plan-boot.o: build/elf64-page-plan.o
	objcopy --redefine-sym f0=elf_plan_f0 "$<" "$@"
build/elf64-page-plan-dishonest-boot.o: build/elf64-page-plan-unsafe.o
	objcopy --redefine-sym f0=elf_plan_f0 "$<" "$@"
# Reuse byte-identical locked HIA full-file ELF layout checker, not a
# bridge-side PHDR substitute. The alternate object is deliberately dishonest.
build/elf64-load-boot.o: build/elf64-load-segments.o
	objcopy --redefine-sym f0=elf_layout_f0 "$<" "$@"
build/elf64-load-dishonest-boot.o: build/elf64-load-unsafe.o
	objcopy --redefine-sym f0=elf_layout_f0 "$<" "$@"
build/elf64-snapshot-boot.o: build/elf64-snapshot.o
	objcopy --redefine-sym f0=elf_snapshot_f0 "$<" "$@"
build/elf64-snapshot-dishonest-boot.o: build/elf64-snapshot-unsafe.o
	objcopy --redefine-sym f0=elf_snapshot_f0 "$<" "$@"
build/elf64-stage-boot.o: build/elf64-stage.o
	objcopy --redefine-sym f0=elf_stage_f0 "$<" "$@"
build/elf64-stage-dishonest-boot.o: build/elf64-stage-unsafe.o
	objcopy --redefine-sym f0=elf_stage_f0 "$<" "$@"

build/boot-elf-plan-hw.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_ELF_PLAN_HW=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-elf-plan-invalid.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_ELF_PLAN_HW=1 -DHEPTAKERNEL_TEST_ELF_PLAN_INVALID=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-elf-plan-noop.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_ELF_PLAN_HW=1 -DHEPTAKERNEL_TEST_ELF_PLAN_NOOP=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-elf-plan-decoy.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_ELF_PLAN_HW=1 -DHEPTAKERNEL_TEST_ELF_PLAN_DECOY=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-elf-plan-overlap.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_ELF_PLAN_HW=1 -DHEPTAKERNEL_TEST_ELF_LAYOUT_OVERLAP=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-elf-plan-layout-liar.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_ELF_PLAN_HW=1 -DHEPTAKERNEL_TEST_ELF_LAYOUT_LIAR=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-elf-plan-snapshot-mutated.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_ELF_PLAN_HW=1 -DHEPTAKERNEL_TEST_ELF_SNAPSHOT_MUTATED=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-elf-plan-snapshot-liar.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_ELF_PLAN_HW=1 -DHEPTAKERNEL_TEST_ELF_SNAPSHOT_LIAR=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-elf-plan-stage-noop.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_ELF_PLAN_HW=1 -DHEPTAKERNEL_TEST_ELF_STAGE_NOOP=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-elf-plan-stage-corrupt.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_ELF_PLAN_HW=1 -DHEPTAKERNEL_TEST_ELF_STAGE_CORRUPT=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-elf-plan-source-isolated.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_ELF_PLAN_HW=1 -DHEPTAKERNEL_TEST_ELF_SOURCE_ISOLATED=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

ELF_PLAN_HW_SUPPORT := $(ELF_PAGE_HW_SUPPORT) build/elf64-page-fill-boot.o build/elf64-snapshot-boot.o build/elf64-stage-boot.o
ELF_PLAN_HW_LIAR_SUPPORT := $(ELF_PAGE_HW_SUPPORT) build/elf64-page-fill-boot.o build/elf64-snapshot-dishonest-boot.o build/elf64-stage-boot.o
ELF_PLAN_HW_STAGE_LIAR_SUPPORT := $(ELF_PAGE_HW_SUPPORT) build/elf64-page-fill-boot.o build/elf64-snapshot-boot.o build/elf64-stage-dishonest-boot.o
build/elf-plan-hw.elf: build/boot-elf-plan-hw.o $(ELF_PLAN_HW_SUPPORT) build/elf64-load-boot.o build/elf64-page-plan-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-elf-plan-hw.o $(ELF_PLAN_HW_SUPPORT) build/elf64-load-boot.o build/elf64-page-plan-boot.o
build/elf-plan-invalid.elf: build/boot-elf-plan-invalid.o $(ELF_PLAN_HW_SUPPORT) build/elf64-load-boot.o build/elf64-page-plan-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-elf-plan-invalid.o $(ELF_PLAN_HW_SUPPORT) build/elf64-load-boot.o build/elf64-page-plan-boot.o
build/elf-plan-noop.elf: build/boot-elf-plan-noop.o $(ELF_PLAN_HW_SUPPORT) build/elf64-load-boot.o build/elf64-page-plan-dishonest-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-elf-plan-noop.o $(ELF_PLAN_HW_SUPPORT) build/elf64-load-boot.o build/elf64-page-plan-dishonest-boot.o
build/elf-plan-decoy.elf: build/boot-elf-plan-decoy.o $(ELF_PLAN_HW_SUPPORT) build/elf64-load-boot.o build/elf64-page-plan-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-elf-plan-decoy.o $(ELF_PLAN_HW_SUPPORT) build/elf64-load-boot.o build/elf64-page-plan-boot.o
build/elf-plan-overlap.elf: build/boot-elf-plan-overlap.o $(ELF_PLAN_HW_SUPPORT) build/elf64-load-boot.o build/elf64-page-plan-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-elf-plan-overlap.o $(ELF_PLAN_HW_SUPPORT) build/elf64-load-boot.o build/elf64-page-plan-boot.o
build/elf-plan-layout-liar.elf: build/boot-elf-plan-layout-liar.o $(ELF_PLAN_HW_SUPPORT) build/elf64-load-dishonest-boot.o build/elf64-page-plan-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-elf-plan-layout-liar.o $(ELF_PLAN_HW_SUPPORT) build/elf64-load-dishonest-boot.o build/elf64-page-plan-boot.o
build/elf-plan-snapshot-mutated.elf: build/boot-elf-plan-snapshot-mutated.o $(ELF_PLAN_HW_SUPPORT) build/elf64-load-boot.o build/elf64-page-plan-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-elf-plan-snapshot-mutated.o $(ELF_PLAN_HW_SUPPORT) build/elf64-load-boot.o build/elf64-page-plan-boot.o
build/elf-plan-snapshot-liar.elf: build/boot-elf-plan-snapshot-liar.o $(ELF_PLAN_HW_LIAR_SUPPORT) build/elf64-load-boot.o build/elf64-page-plan-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-elf-plan-snapshot-liar.o $(ELF_PLAN_HW_LIAR_SUPPORT) build/elf64-load-boot.o build/elf64-page-plan-boot.o
build/elf-plan-stage-noop.elf: build/boot-elf-plan-stage-noop.o $(ELF_PLAN_HW_STAGE_LIAR_SUPPORT) build/elf64-load-boot.o build/elf64-page-plan-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-elf-plan-stage-noop.o $(ELF_PLAN_HW_STAGE_LIAR_SUPPORT) build/elf64-load-boot.o build/elf64-page-plan-boot.o
build/elf-plan-stage-corrupt.elf: build/boot-elf-plan-stage-corrupt.o $(ELF_PLAN_HW_SUPPORT) build/elf64-load-boot.o build/elf64-page-plan-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-elf-plan-stage-corrupt.o $(ELF_PLAN_HW_SUPPORT) build/elf64-load-boot.o build/elf64-page-plan-boot.o
build/elf-plan-source-isolated.elf: build/boot-elf-plan-source-isolated.o $(ELF_PLAN_HW_SUPPORT) build/elf64-load-boot.o build/elf64-page-plan-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" build/boot-elf-plan-source-isolated.o $(ELF_PLAN_HW_SUPPORT) build/elf64-load-boot.o build/elf64-page-plan-boot.o
build/elf-plan-%-multiboot.elf: build/elf-plan-%.elf
	objcopy -O elf32-i386 "$<" "$@"

test-elf64-page-plan-hw: test-elf64-stage test-elf64-snapshot test-elf64-load-segments build/elf-plan-stage-noop-multiboot.elf build/elf-plan-stage-corrupt-multiboot.elf build/elf-plan-source-isolated-multiboot.elf build/elf-plan-snapshot-mutated-multiboot.elf build/elf-plan-snapshot-liar-multiboot.elf build/elf-plan-hw-multiboot.elf build/elf-plan-invalid-multiboot.elf build/elf-plan-noop-multiboot.elf build/elf-plan-decoy-multiboot.elf build/elf-plan-overlap-multiboot.elf build/elf-plan-layout-liar-multiboot.elf
	@set -eu; a=$$(mktemp build/.elf-plan-text-a.XXXXXX); b=$$(mktemp build/.elf-plan-text-b.XXXXXX); \
	  trap 'rm -f "$$a" "$$b"' EXIT HUP INT TERM; \
	  sha256sum build/elf64-page-plan.o build/elf64-page-plan-unsafe.o \
	    build/elf64-load-segments.o build/elf64-load-unsafe.o \
	    build/elf64-snapshot.o build/elf64-snapshot-unsafe.o build/elf64-stage.o build/elf64-stage-unsafe.o > build/elf-plan-native-inputs.sha256; \
	  objcopy -O binary --only-section=.text build/elf64-page-plan.o "$$a"; \
	  objcopy -O binary --only-section=.text build/elf64-page-plan-boot.o "$$b"; cmp "$$a" "$$b"; \
	  objcopy -O binary --only-section=.text build/elf64-page-plan-unsafe.o "$$a"; \
	  objcopy -O binary --only-section=.text build/elf64-page-plan-dishonest-boot.o "$$b"; cmp "$$a" "$$b"; \
	  objcopy -O binary --only-section=.text build/elf64-load-segments.o "$$a"; \
	  objcopy -O binary --only-section=.text build/elf64-load-boot.o "$$b"; cmp "$$a" "$$b"; \
	  objcopy -O binary --only-section=.text build/elf64-load-unsafe.o "$$a"; \
	  objcopy -O binary --only-section=.text build/elf64-load-dishonest-boot.o "$$b"; cmp "$$a" "$$b"; \
	  objcopy -O binary --only-section=.text build/elf64-snapshot.o "$$a"; \
	  objcopy -O binary --only-section=.text build/elf64-snapshot-boot.o "$$b"; cmp "$$a" "$$b"; \
	  objcopy -O binary --only-section=.text build/elf64-snapshot-unsafe.o "$$a"; \
	  objcopy -O binary --only-section=.text build/elf64-snapshot-dishonest-boot.o "$$b"; cmp "$$a" "$$b"; \
	  objcopy -O binary --only-section=.text build/elf64-stage.o "$$a"; \
	  objcopy -O binary --only-section=.text build/elf64-stage-boot.o "$$b"; cmp "$$a" "$$b"; \
	  objcopy -O binary --only-section=.text build/elf64-stage-unsafe.o "$$a"; \
	  objcopy -O binary --only-section=.text build/elf64-stage-dishonest-boot.o "$$b"; cmp "$$a" "$$b"; \
	  sha256sum --check build/elf-plan-native-inputs.sha256
	timeout 160 $(PYTHON) tests/test_elf64_page_plan_qemu.py --qemu "$(QEMU)"


# Native HIA copies a bounded ELF byte stream to a caller-owned staging buffer.
# The caller still owes stable input, nonaliasing and exclusive staging ownership.
.PHONY: test-elf64-stage
build/elf64-stage.o: src/elf64_snapshot_stage.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.elf-stage.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	compiler=$$(command -v "$(HEPTA_COMPILER)"); \
	env -i PATH='' "$$compiler" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/elf64-stage.so: build/elf64-stage.o
	ld -shared -z noexecstack -o "$@" "$<"

build/elf64-stage-unsafe.o: tests/negative/elf64_snapshot_stage_noop.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.elf-stage-unsafe.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/elf64-stage-unsafe.so: build/elf64-stage-unsafe.o
	ld -shared -z noexecstack -o "$@" "$<"

test-elf64-stage: build/elf64-stage.so build/elf64-stage-unsafe.so
	timeout 90 $(PYTHON) tests/test_elf64_snapshot_stage.py build/elf64-stage.so --object build/elf64-stage.o
	$(PYTHON) tests/test_elf64_snapshot_stage.py build/elf64-stage-unsafe.so --expect-unsafe
	@set -eu; a=$$(mktemp build/.stage-repro-a.XXXXXX); b=$$(mktemp build/.stage-repro-b.XXXXXX); \
	trap 'rm -f "$$a" "$$b"' EXIT HUP INT TERM; \
	env -i PATH='' "$(HEPTA_COMPILER)" < src/elf64_snapshot_stage.hepta > "$$a"; \
	env -i PATH='' "$(HEPTA_COMPILER)" < src/elf64_snapshot_stage.hepta > "$$b"; \
	cmp build/elf64-stage.o "$$a"; cmp "$$a" "$$b"

test: test-elf64-stage

# HIA native single-owner two-leaf PTE preflight: all validation before either store.
.PHONY: test-x86-pt-pair
build/x86-pt-pair.o: src/x86_pt_pair_commit.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.x86-pt-pair.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"
build/x86-pt-pair.so: build/x86-pt-pair.o
	ld -shared -z noexecstack -o "$@" "$<"
build/x86-pt-pair-unsafe.o: tests/negative/x86_pt_pair_noop.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.x86-pt-pair-unsafe.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"
build/x86-pt-pair-unsafe.so: build/x86-pt-pair-unsafe.o
	ld -shared -z noexecstack -o "$@" "$<"
test-x86-pt-pair: build/x86-pt-pair.so build/x86-pt-pair-unsafe.so
	timeout 90 $(PYTHON) tests/test_x86_pt_pair_commit.py build/x86-pt-pair.so --object build/x86-pt-pair.o
	$(PYTHON) tests/test_x86_pt_pair_commit.py build/x86-pt-pair-unsafe.so --expect-unsafe
	@set -eu; a=$$(mktemp build/.pt-pair-a.XXXXXX); b=$$(mktemp build/.pt-pair-b.XXXXXX); \
	trap 'rm -f "$$a" "$$b"' EXIT HUP INT TERM; \
	env -i PATH='' "$(HEPTA_COMPILER)" < src/x86_pt_pair_commit.hepta > "$$a"; \
	env -i PATH='' "$(HEPTA_COMPILER)" < src/x86_pt_pair_commit.hepta > "$$b"; \
	cmp build/x86-pt-pair.o "$$a"; cmp "$$a" "$$b"


# Real isolated x86-64 hardware experiment: native HIA PTE pair commits
# two different physical pages. Only the observer supplies CR3/PDE effects.
.PHONY: test-pt-pair-hw
build/pt-pair-boot.o: build/x86-pt-pair.o
	objcopy --redefine-sym f0=pt_pair_f0 "$<" "$@"
build/pt-pair-unsafe-boot.o: build/x86-pt-pair-unsafe.o
	objcopy --redefine-sym f0=pt_pair_f0 "$<" "$@"
build/boot-pt-pair-hw.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PT_PAIR_HW=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-pt-pair-stale.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PT_PAIR_STALE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-pt-pair-liar.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PT_PAIR_LIAR=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
PT_PAIR_HW_SUPPORT := build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o
build/pt-pair-hw.elf: build/boot-pt-pair-hw.o $(PT_PAIR_HW_SUPPORT) build/pt-pair-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" $< $(PT_PAIR_HW_SUPPORT) build/pt-pair-boot.o
build/pt-pair-stale.elf: build/boot-pt-pair-stale.o $(PT_PAIR_HW_SUPPORT) build/pt-pair-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" $< $(PT_PAIR_HW_SUPPORT) build/pt-pair-boot.o
build/pt-pair-liar.elf: build/boot-pt-pair-liar.o $(PT_PAIR_HW_SUPPORT) build/pt-pair-unsafe-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" $< $(PT_PAIR_HW_SUPPORT) build/pt-pair-unsafe-boot.o
build/pt-pair-%-multiboot.elf: build/pt-pair-%.elf
	objcopy -O elf32-i386 "$<" "$@"
test-pt-pair-hw: build/pt-pair-hw-multiboot.elf build/pt-pair-stale-multiboot.elf build/pt-pair-liar-multiboot.elf
	$(PYTHON) tests/test_x86_pt_pair_qemu.py --qemu "$(QEMU)"

test: test-pt-pair-hw
test-boot: test-pt-pair-hw

# Genuine HIA offline shadow 4KiB table construction; no live parent publication.
.PHONY: test-x86-pt-pair-shadow
build/x86-pt-pair-shadow.o: src/x86_pt_pair_shadow.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.x86-pt-pair-shadow.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"
build/x86-pt-pair-shadow.so: build/x86-pt-pair-shadow.o
	ld -shared -z noexecstack -o "$@" "$<"
build/x86-pt-pair-shadow-unsafe.o: tests/negative/x86_pt_pair_shadow_noop.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.x86-pt-pair-shadow-unsafe.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"
build/x86-pt-pair-shadow-unsafe.so: build/x86-pt-pair-shadow-unsafe.o
	ld -shared -z noexecstack -o "$@" "$<"
test-x86-pt-pair-shadow: build/x86-pt-pair-shadow.so build/x86-pt-pair-shadow-unsafe.so
	timeout 90 $(PYTHON) tests/test_x86_pt_pair_shadow.py build/x86-pt-pair-shadow.so --object build/x86-pt-pair-shadow.o
	$(PYTHON) tests/test_x86_pt_pair_shadow.py build/x86-pt-pair-shadow-unsafe.so --expect-unsafe
	@set -eu; a=$$(mktemp build/.pair-shadow-a.XXXXXX); b=$$(mktemp build/.pair-shadow-b.XXXXXX); \
	trap 'rm -f "$$a" "$$b"' EXIT HUP INT TERM; \
	env -i PATH='' "$(HEPTA_COMPILER)" < src/x86_pt_pair_shadow.hepta > "$$a"; \
	env -i PATH='' "$(HEPTA_COMPILER)" < src/x86_pt_pair_shadow.hepta > "$$b"; \
	cmp build/x86-pt-pair-shadow.o "$$a"; cmp "$$a" "$$b"

test: test-x86-pt-pair-shadow

# Genuine Core v8 HIA constructs a separate 4KiB table before a NON-HIA
# single parent PDE publish; test all QEMU failure paths independently.
.PHONY: test-pt-shadow-hw
build/pt-shadow-boot.o: build/x86-pt-pair-shadow.o
	objcopy --redefine-sym f0=pt_shadow_f0 "$<" "$@"
build/pt-shadow-unsafe-boot.o: build/x86-pt-pair-shadow-unsafe.o
	objcopy --redefine-sym f0=pt_shadow_f0 "$<" "$@"
build/boot-pt-shadow-hw.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PT_SHADOW_HW=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-pt-shadow-stale.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PT_SHADOW_STALE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-pt-shadow-liar.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PT_SHADOW_LIAR=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-pt-shadow-tamper.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_PT_SHADOW_TAMPER=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
PT_SHADOW_HW_SUPPORT := $(PT_PAIR_HW_SUPPORT)
build/pt-shadow-hw.elf: build/boot-pt-shadow-hw.o $(PT_SHADOW_HW_SUPPORT) build/pt-shadow-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" $< $(PT_SHADOW_HW_SUPPORT) build/pt-shadow-boot.o
build/pt-shadow-stale.elf: build/boot-pt-shadow-stale.o $(PT_SHADOW_HW_SUPPORT) build/pt-shadow-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" $< $(PT_SHADOW_HW_SUPPORT) build/pt-shadow-boot.o
build/pt-shadow-liar.elf: build/boot-pt-shadow-liar.o $(PT_SHADOW_HW_SUPPORT) build/pt-shadow-unsafe-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" $< $(PT_SHADOW_HW_SUPPORT) build/pt-shadow-unsafe-boot.o
build/pt-shadow-tamper.elf: build/boot-pt-shadow-tamper.o $(PT_SHADOW_HW_SUPPORT) build/pt-shadow-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" $< $(PT_SHADOW_HW_SUPPORT) build/pt-shadow-boot.o
build/pt-shadow-%-multiboot.elf: build/pt-shadow-%.elf
	objcopy -O elf32-i386 "$<" "$@"
test-pt-shadow-hw: build/pt-shadow-hw-multiboot.elf build/pt-shadow-stale-multiboot.elf build/pt-shadow-liar-multiboot.elf build/pt-shadow-tamper-multiboot.elf
	$(PYTHON) tests/test_x86_pt_shadow_qemu.py --qemu "$(QEMU)"
test: test-pt-shadow-hw
test-boot: test-pt-shadow-hw

# Shadow leaf table publish preflight: PMM occupancy, frame geometry and parent word.
# No CRx operation, atomic compare/exchange, or authenticated owner in this stage.
build/x86-shadow-frame-admit.o: src/x86_shadow_frame_admit.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.shadow-owner.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	env -i PATH= "$(HEPTA_COMPILER)" < "$<" > "$$tmp"; \
	test -s "$$tmp"; test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"

build/x86-shadow-frame-admit.so: build/x86-shadow-frame-admit.o
	ld -shared -z noexecstack -o "$@" "$<"

build/x86-shadow-frame-admit-unsafe.o: tests/negative/x86_shadow_frame_admit_noop.hepta | build check-compiler
	"$(HEPTA_COMPILER)" < "$<" > "$@"

build/x86-shadow-frame-admit-unsafe.so: build/x86-shadow-frame-admit-unsafe.o
	ld -shared -z noexecstack -o "$@" "$<"

.PHONY: test-x86-shadow-frame-admit
test-x86-shadow-frame-admit: build/x86-shadow-frame-admit.so build/x86-shadow-frame-admit-unsafe.so
	@set -eu; tmp=$$(mktemp build/.shadow-owner-identity.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	env -i PATH= "$(HEPTA_COMPILER)" < src/x86_shadow_frame_admit.hepta > "$$tmp"; \
	cmp "$$tmp" build/x86-shadow-frame-admit.o
	timeout 90 $(PYTHON) tests/test_x86_shadow_frame_admit.py build/x86-shadow-frame-admit.so --object build/x86-shadow-frame-admit.o
	$(PYTHON) tests/test_x86_shadow_frame_admit.py build/x86-shadow-frame-admit-unsafe.so --expect-unsafe

# End-to-end QEMU frame-owner preflight on two ACTUALLY HIA-allocated pages.
# HIA constructs the offline shadow, HIA verifies the current PMM snapshot
# and only the expressly non-HIA isolated bridge performs PDE/CR3 publication.
.PHONY: test-shadow-owner-hw
build/shadow-owner-admit-boot.o: build/x86-shadow-frame-admit.o
	objcopy --redefine-sym f0=shadow_admit_f0 "$<" "$@"
build/shadow-owner-admit-unsafe-boot.o: build/x86-shadow-frame-admit-unsafe.o
	objcopy --redefine-sym f0=shadow_admit_f0 "$<" "$@"
build/boot-shadow-owner-hw.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_SHADOW_OWNER_HW=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-shadow-owner-stale.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_SHADOW_OWNER_STALE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-shadow-owner-liar.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_SHADOW_OWNER_LIAR=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-shadow-owner-bitmap.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_SHADOW_OWNER_BITMAP=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-shadow-owner-recheck.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_SHADOW_OWNER_RECHECK=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-shadow-owner-free-stale.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_SHADOW_OWNER_FREE_STALE=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-shadow-owner-free-liar.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_SHADOW_OWNER_FREE_LIAR=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-shadow-owner-post-tail.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_SHADOW_OWNER_POST_TAIL=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"
build/boot-shadow-owner-post-balanced.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_SHADOW_OWNER_POST_BALANCED=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

SHADOW_OWNER_HW_SUPPORT := $(PT_SHADOW_HW_SUPPORT) build/pt-shadow-boot.o
SHADOW_OWNER_PMM_CHECK := build/pmm-bitmap-boot.o
build/shadow-owner-hw.elf: build/boot-shadow-owner-hw.o $(SHADOW_OWNER_HW_SUPPORT) build/shadow-owner-admit-boot.o $(SHADOW_OWNER_PMM_CHECK) arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" $< $(SHADOW_OWNER_HW_SUPPORT) build/shadow-owner-admit-boot.o $(SHADOW_OWNER_PMM_CHECK)
build/shadow-owner-stale.elf: build/boot-shadow-owner-stale.o $(SHADOW_OWNER_HW_SUPPORT) build/shadow-owner-admit-boot.o $(SHADOW_OWNER_PMM_CHECK) arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" $< $(SHADOW_OWNER_HW_SUPPORT) build/shadow-owner-admit-boot.o $(SHADOW_OWNER_PMM_CHECK)
build/shadow-owner-bitmap.elf: build/boot-shadow-owner-bitmap.o $(SHADOW_OWNER_HW_SUPPORT) build/shadow-owner-admit-boot.o $(SHADOW_OWNER_PMM_CHECK) arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" $< $(SHADOW_OWNER_HW_SUPPORT) build/shadow-owner-admit-boot.o $(SHADOW_OWNER_PMM_CHECK)
build/shadow-owner-recheck.elf: build/boot-shadow-owner-recheck.o $(SHADOW_OWNER_HW_SUPPORT) build/shadow-owner-admit-boot.o $(SHADOW_OWNER_PMM_CHECK) arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" $< $(SHADOW_OWNER_HW_SUPPORT) build/shadow-owner-admit-boot.o $(SHADOW_OWNER_PMM_CHECK)
build/shadow-owner-liar.elf: build/boot-shadow-owner-liar.o $(SHADOW_OWNER_HW_SUPPORT) build/shadow-owner-admit-unsafe-boot.o $(SHADOW_OWNER_PMM_CHECK) arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" $< $(SHADOW_OWNER_HW_SUPPORT) build/shadow-owner-admit-unsafe-boot.o $(SHADOW_OWNER_PMM_CHECK)
build/shadow-owner-free-stale.elf: build/boot-shadow-owner-free-stale.o $(SHADOW_OWNER_HW_SUPPORT) build/shadow-owner-admit-boot.o $(SHADOW_OWNER_PMM_CHECK) arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" $< $(SHADOW_OWNER_HW_SUPPORT) build/shadow-owner-admit-boot.o $(SHADOW_OWNER_PMM_CHECK)
build/shadow-owner-free-liar.elf: build/boot-shadow-owner-free-liar.o $(SHADOW_OWNER_HW_SUPPORT) build/shadow-owner-admit-boot.o build/pmm-bitmap-dishonest-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" $< $(SHADOW_OWNER_HW_SUPPORT) build/shadow-owner-admit-boot.o build/pmm-bitmap-dishonest-boot.o
build/shadow-owner-post-tail.elf: build/boot-shadow-owner-post-tail.o $(SHADOW_OWNER_HW_SUPPORT) build/shadow-owner-admit-boot.o $(SHADOW_OWNER_PMM_CHECK) arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" $< $(SHADOW_OWNER_HW_SUPPORT) build/shadow-owner-admit-boot.o $(SHADOW_OWNER_PMM_CHECK)
build/shadow-owner-post-balanced.elf: build/boot-shadow-owner-post-balanced.o $(SHADOW_OWNER_HW_SUPPORT) build/shadow-owner-admit-boot.o $(SHADOW_OWNER_PMM_CHECK) arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" $< $(SHADOW_OWNER_HW_SUPPORT) build/shadow-owner-admit-boot.o $(SHADOW_OWNER_PMM_CHECK)
build/shadow-owner-%-multiboot.elf: build/shadow-owner-%.elf
	objcopy -O elf32-i386 "$<" "$@"

test-shadow-owner-hw: build/shadow-owner-hw-multiboot.elf build/shadow-owner-stale-multiboot.elf build/shadow-owner-liar-multiboot.elf build/shadow-owner-bitmap-multiboot.elf build/shadow-owner-recheck-multiboot.elf build/shadow-owner-free-stale-multiboot.elf build/shadow-owner-free-liar-multiboot.elf build/shadow-owner-post-tail-multiboot.elf build/shadow-owner-post-balanced-multiboot.elf
	$(PYTHON) tests/test_x86_shadow_owner_qemu.py --qemu "$(QEMU)"

test: test-shadow-owner-hw
test-boot: test-shadow-owner-hw
