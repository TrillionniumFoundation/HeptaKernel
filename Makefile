SHELL := /bin/sh
HEPTA_COMPILER ?= hia-native-compiler
QEMU ?= qemu-system-x86_64
PYTHON ?= python3
COMPILER_SHA256 := 87c247e4d1c3c9a449d2947fd4227fdc186d519bffd203a04cafce7861a4ed54

.PHONY: test-pt-downgrade-single-byte test-x86-pt-user-revoke test-pt-report-isolation test-x86-pt-nx-protect test-x86-pt-write-protect test-x86-pt-revoke test-x86-access-gate test-x86-walk4-physical test-x86-walk4-auto test-x86-walk4-huge test-x86-walk4-indexed test-x86-cr3-gate test-x86-upper-user all check-compiler test test-x86-pde-2m test-x86-pdpt-1g test-native test-boot test-guard-pages test-memory-map test-arenas test-owner-binding test-reservations test-x86-pte test-x86-pt-commit test-x86-pt-revoke test-x86-pf-gate test-x86-idt test-x86-user-gdt test-x86-tss-gdt test-x86-tss-state test-closure test-linux-inventory record-build full-acceptance clean

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

PDPT_1G_BOOT_SUPPORT := build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/pdpt-1g-boot.o

build/pdpt-1g-%.elf: build/boot-pdpt-1g-%.o $(PDPT_1G_BOOT_SUPPORT) arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o "$@" "$<" $(PDPT_1G_BOOT_SUPPORT)

build/pdpt-1g-%-multiboot.elf: build/pdpt-1g-%.elf
	objcopy -O elf32-i386 "$<" "$@"

test-boot: build/pdpt-1g-hw-multiboot.elf build/pdpt-1g-stale-multiboot.elf build/pdpt-1g-decoy-multiboot.elf build/us-fault-multiboot.elf build/us-stale-multiboot.elf build/us-bypass-multiboot.elf build/pt-nx-fault-multiboot.elf build/pt-nx-stale-multiboot.elf build/pt-nx-bypass-multiboot.elf build/pt-protect-fault-multiboot.elf build/pt-protect-stale-multiboot.elf build/pt-protect-bypass-multiboot.elf build/pt-revoke-fault-multiboot.elf build/pt-revoke-stale-multiboot.elf build/pt-revoke-bypass-multiboot.elf build/ring3-upper-stale-multiboot.elf build/user-gdt-conflict-multiboot.elf build/ring3-rsp0-multiboot.elf build/ring3-rsp0-decoy-multiboot.elf build/tss-rsp0-conflict-multiboot.elf build/tss-state-conflict-multiboot.elf build/tss-conflict-multiboot.elf build/idt-conflict-multiboot.elf build/pf-corrupt-multiboot.elf build/pt-commit-conflict-multiboot.elf build/wp-fault-multiboot.elf build/wp-bypass-multiboot.elf build/nx-fault-multiboot.elf build/nx-bypass-multiboot.elf build/pte-unsafe-multiboot.elf build/reservation-conflict-multiboot.elf build/reservation-bypass-multiboot.elf build/owner-alias-multiboot.elf build/arena-bypass-multiboot.elf build/kernel-multiboot.elf build/success_stub-multiboot.elf build/bounds_trap-multiboot.elf build/e820-reserved-multiboot.elf build/e820-bypass-multiboot.elf build/e820-persistent-multiboot.elf build/e820-persistent-bypass-multiboot.elf build/ring3-pde-stale-multiboot.elf
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

record-build: build/us-fault-multiboot.elf build/us-stale-multiboot.elf build/us-bypass-multiboot.elf build/x86-pt-user-revoke.so build/x86-pt-user-revoke.o build/pt-nx-fault-multiboot.elf build/pt-nx-stale-multiboot.elf build/pt-nx-bypass-multiboot.elf build/pt-nx-boot.o build/x86-pt-nx-protect.so build/x86-pt-nx-protect.o build/pt-protect-boot.o build/pt-protect-fault-multiboot.elf build/pt-protect-stale-multiboot.elf build/pt-protect-bypass-multiboot.elf build/x86-pt-write-protect.so build/x86-pt-write-protect.o build/pt-revoke-boot.o build/pt-revoke-fault-multiboot.elf build/pt-revoke-stale-multiboot.elf build/pt-revoke-bypass-multiboot.elf build/upper-user-boot.o build/ring3-upper-stale-multiboot.elf build/x86-upper-user.so build/x86-user-gdt.so build/user-gdt-boot.o build/boot-user-gdt-conflict.o build/user-gdt-conflict-multiboot.elf build/boot-ring3-rsp0.o build/boot-ring3-rsp0-decoy.o build/ring3-rsp0-multiboot.elf build/ring3-rsp0-decoy-multiboot.elf build/boot-tss-rsp0-conflict.o build/tss-rsp0-conflict-multiboot.elf build/boot-tss-state-conflict.o build/tss-state-conflict-multiboot.elf build/boot-tss-conflict.o build/tss-conflict-multiboot.elf build/x86-tss-gdt.so build/boot-idt-conflict.o build/idt-conflict-multiboot.elf build/idt-gate-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/x86-idt.so build/pf-corrupt-multiboot.elf build/boot-pf-corrupt.o build/x86-pf-gate.so build/pf-gate-boot.o build/pt-commit-conflict-multiboot.elf build/x86-pt-commit.so build/wp-fault-multiboot.elf build/wp-bypass-multiboot.elf build/nx-fault-multiboot.elf build/nx-bypass-multiboot.elf build/pte-unsafe-multiboot.elf build/pte-boot.o build/pt-commit-boot.o build/x86-pte.so build/reservation-conflict-multiboot.elf build/reservation-bypass-multiboot.elf build/reservation-gate.so build/owner-binding.so build/owner-boot.o build/owner-alias-multiboot.elf build/arena-bypass-multiboot.elf build/arena-router.so build/kernel-host.so build/kernel-multiboot.elf build/e820-reserved-multiboot.elf build/e820-bypass-multiboot.elf build/e820-persistent-multiboot.elf build/e820-persistent-bypass-multiboot.elf build/x86-pde-2m.o build/x86-pde-2m.so build/x86-pdpt-1g.o build/x86-pdpt-1g.so build/pde-2m-boot.o build/boot-ring3-pde-stale.o build/ring3-pde-stale-multiboot.elf
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

test: test-pt-downgrade-single-byte test-x86-pt-user-revoke test-pt-report-isolation test-x86-pt-nx-protect test-x86-pt-write-protect test-x86-pt-revoke test-x86-access-gate test-x86-walk4-physical test-x86-walk4-auto test-x86-walk4-huge test-x86-walk4-indexed test-x86-walk4 test-x86-cr3-gate test-x86-upper-user test-x86-pde-2m test-x86-pdpt-1g test-x86-user-gdt test-x86-tss-state test-x86-tss-gdt test-native test-guard-pages test-memory-map test-arenas test-owner-binding test-reservations test-x86-pte test-x86-pt-commit test-x86-pf-gate test-x86-idt test-boot test-closure test-linux-inventory record-build

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
