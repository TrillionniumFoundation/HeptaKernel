# Native HIA, READ-ONLY supplied per-CPU TLB-ack snapshot admission.
# No IPI, privileged INVLPG, authenticated CR3, atomic acquire or frame free.
.PHONY: test-x86-shootdown-admit
build/x86-shootdown-admit.o: src/x86_shootdown_admit.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.shootdown.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"
build/x86-shootdown-admit.so: build/x86-shootdown-admit.o
	ld -shared -z noexecstack -o "$@" "$<"
build/x86-shootdown-liar.o: tests/negative/x86_shootdown_allow_all.hepta | build check-compiler
	"$(HEPTA_COMPILER)" < "$<" > "$@"
build/x86-shootdown-liar.so: build/x86-shootdown-liar.o
	ld -shared -z noexecstack -o "$@" "$<"
test-x86-shootdown-admit: build/x86-shootdown-admit.so build/x86-shootdown-liar.so
	@set -eu; a=$$(mktemp build/.shootdown-a.XXXXXX); b=$$(mktemp build/.shootdown-b.XXXXXX); \
	trap 'rm -f "$$a" "$$b"' EXIT HUP INT TERM; \
	env -i PATH= "$(HEPTA_COMPILER)" < src/x86_shootdown_admit.hepta > "$$a"; \
	env -i PATH= "$(HEPTA_COMPILER)" < src/x86_shootdown_admit.hepta > "$$b"; \
	cmp "$$a" "$$b"; cmp "$$a" build/x86-shootdown-admit.o
	timeout 90 $(PYTHON) tests/test_x86_shootdown_admit.py build/x86-shootdown-admit.so
	$(PYTHON) tests/test_x86_shootdown_admit.py build/x86-shootdown-liar.so --dishonest
test: test-x86-shootdown-admit

# Page-address bound successor: each UNTRUSTED ack row also binds the exact VA.
.PHONY: test-x86-shootdown-page-bound
build/x86-shootdown-page-bound.o: src/x86_shootdown_page_bound.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.page-bound.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"
build/x86-shootdown-page-bound.so: build/x86-shootdown-page-bound.o
	ld -shared -z noexecstack -o "$@" "$<"
build/x86-shootdown-page-bound-liar.o: tests/negative/x86_shootdown_page_bound_allow_all.hepta | build check-compiler
	"$(HEPTA_COMPILER)" < "$<" > "$@"
build/x86-shootdown-page-bound-liar.so: build/x86-shootdown-page-bound-liar.o
	ld -shared -z noexecstack -o "$@" "$<"
test-x86-shootdown-page-bound: build/x86-shootdown-page-bound.so build/x86-shootdown-page-bound-liar.so
	@set -eu; a=$$(mktemp build/.page-bound-a.XXXXXX); b=$$(mktemp build/.page-bound-b.XXXXXX); \
	trap 'rm -f "$$a" "$$b"' EXIT HUP INT TERM; \
	env -i PATH= "$(HEPTA_COMPILER)" < src/x86_shootdown_page_bound.hepta > "$$a"; \
	env -i PATH= "$(HEPTA_COMPILER)" < src/x86_shootdown_page_bound.hepta > "$$b"; \
	cmp "$$a" "$$b"; cmp "$$a" build/x86-shootdown-page-bound.o
	timeout 90 $(PYTHON) tests/test_x86_shootdown_page_bound.py build/x86-shootdown-page-bound.so
	$(PYTHON) tests/test_x86_shootdown_page_bound.py build/x86-shootdown-page-bound-liar.so --dishonest
test: test-x86-shootdown-page-bound
