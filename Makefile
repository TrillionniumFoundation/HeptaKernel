SHELL := /bin/sh
HEPTA_COMPILER ?= hia-native-compiler
QEMU ?= qemu-system-x86_64
PYTHON ?= python3
COMPILER_SHA256 := 87c247e4d1c3c9a449d2947fd4227fdc186d519bffd203a04cafce7861a4ed54

.PHONY: all check-compiler test test-native test-boot test-guard-pages test-memory-map test-arenas test-owner-binding test-reservations test-x86-pte test-x86-pt-commit test-x86-pf-gate test-x86-idt test-x86-user-gdt test-x86-tss-gdt test-x86-tss-state test-closure test-linux-inventory record-build full-acceptance clean

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
	@set -eu; tmp=$(mktemp build/.x86-user-gdt.XXXXXX); trap 'rm -f "$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$tmp"; test -s "$tmp"; \\
	test -z "$(nm -u "$tmp")"; mv "$tmp" "$@"

build/x86-user-gdt.so: build/x86-user-gdt.o
	ld -shared -z noexecstack -o "$@" "$<"

build/user-gdt-boot.o: build/x86-user-gdt.o
	objcopy --redefine-sym f0=user_gdt_f0 "$<" "$@"

test-x86-user-gdt: build/x86-user-gdt.so build/e820-allow-all.so
	timeout 90 $(PYTHON) tests/test_x86_user_gdt.py build/x86-user-gdt.so
	$(PYTHON) tests/test_x86_user_gdt.py build/e820-allow-all.so --expect-unsafe

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

build/boot-ring3-rsp0-decoy.o: arch/x86_64/boot.S build/boot-cases.bin
	cc -DHEPTAKERNEL_TEST_RSP0_DECOY=1 -c -m64 -nostdlib -fno-pie -o "$@" "$<"

build/ring3-rsp0-multiboot.elf: build/boot-ring3-rsp0.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/ring3-rsp0.elf build/boot-ring3-rsp0.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o
	objcopy -O elf32-i386 build/ring3-rsp0.elf "$@"

build/ring3-rsp0-decoy-multiboot.elf: build/boot-ring3-rsp0-decoy.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o arch/x86_64/linker.ld
	ld -nostdlib -z noexecstack -z max-page-size=0x1000 -T arch/x86_64/linker.ld -o build/ring3-rsp0-decoy.elf build/boot-ring3-rsp0-decoy.o build/kernel.o build/e820-boot.o build/arena-boot.o build/owner-boot.o build/reservation-boot.o build/pte-boot.o build/pt-commit-boot.o build/pf-gate-boot.o build/idt-gate-boot.o build/user-gdt-boot.o build/tss-gdt-boot.o build/tss-state-boot.o
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

test-boot: build/user-gdt-conflict-multiboot.elf build/ring3-rsp0-multiboot.elf build/ring3-rsp0-decoy-multiboot.elf build/tss-rsp0-conflict-multiboot.elf build/tss-state-conflict-multiboot.elf build/tss-conflict-multiboot.elf build/idt-conflict-multiboot.elf build/pf-corrupt-multiboot.elf build/pt-commit-conflict-multiboot.elf build/wp-fault-multiboot.elf build/wp-bypass-multiboot.elf build/nx-fault-multiboot.elf build/nx-bypass-multiboot.elf build/pte-unsafe-multiboot.elf build/reservation-conflict-multiboot.elf build/reservation-bypass-multiboot.elf build/owner-alias-multiboot.elf build/arena-bypass-multiboot.elf build/kernel-multiboot.elf build/success_stub-multiboot.elf build/bounds_trap-multiboot.elf build/e820-reserved-multiboot.elf build/e820-bypass-multiboot.elf build/e820-persistent-multiboot.elf build/e820-persistent-bypass-multiboot.elf
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

record-build: build/x86-user-gdt.so build/user-gdt-boot.o build/boot-user-gdt-conflict.o build/user-gdt-conflict-multiboot.elf build/boot-ring3-rsp0.o build/boot-ring3-rsp0-decoy.o build/ring3-rsp0-multiboot.elf build/ring3-rsp0-decoy-multiboot.elf build/boot-tss-rsp0-conflict.o build/tss-rsp0-conflict-multiboot.elf build/boot-tss-state-conflict.o build/tss-state-conflict-multiboot.elf build/boot-tss-conflict.o build/tss-conflict-multiboot.elf build/x86-tss-gdt.so build/boot-idt-conflict.o build/idt-conflict-multiboot.elf build/idt-gate-boot.o build/tss-gdt-boot.o build/tss-state-boot.o build/x86-idt.so build/pf-corrupt-multiboot.elf build/boot-pf-corrupt.o build/x86-pf-gate.so build/pf-gate-boot.o build/pt-commit-conflict-multiboot.elf build/x86-pt-commit.so build/wp-fault-multiboot.elf build/wp-bypass-multiboot.elf build/nx-fault-multiboot.elf build/nx-bypass-multiboot.elf build/pte-unsafe-multiboot.elf build/pte-boot.o build/pt-commit-boot.o build/x86-pte.so build/reservation-conflict-multiboot.elf build/reservation-bypass-multiboot.elf build/reservation-gate.so build/owner-binding.so build/owner-boot.o build/owner-alias-multiboot.elf build/arena-bypass-multiboot.elf build/arena-router.so build/kernel-host.so build/kernel-multiboot.elf build/e820-reserved-multiboot.elf build/e820-bypass-multiboot.elf build/e820-persistent-multiboot.elf build/e820-persistent-bypass-multiboot.elf
	$(PYTHON) tools/record_build.py --compiler "$(HEPTA_COMPILER)"

test-closure:
	$(PYTHON) tests/test_closure.py

test-linux-inventory:
	$(PYTHON) tests/test_linux_inventory.py

test: test-x86-user-gdt test-x86-tss-state test-x86-tss-gdt test-native test-guard-pages test-memory-map test-arenas test-owner-binding test-reservations test-x86-pte test-x86-pt-commit test-x86-pf-gate test-x86-idt test-boot test-closure test-linux-inventory record-build

full-acceptance:
	$(PYTHON) tools/check_closure.py

clean:
	rm -rf build build/x86-user-gdt.o build/x86-user-gdt.so build/user-gdt-boot.o build/user-gdt-conflict.elf build/user-gdt-conflict-multiboot.elf build/boot-user-gdt-conflict.o
