# Full remote cohort successor: derives all remote targets and rejects epoch replay.
.PHONY: test-x86-shootdown-full-cohort
build/x86-shootdown-full-cohort.o: src/x86_shootdown_full_cohort.hepta | build check-compiler
	@set -eu; tmp=$$(mktemp build/.full-cohort.XXXXXX); trap 'rm -f "$$tmp"' EXIT HUP INT TERM; \
	"$(HEPTA_COMPILER)" < "$<" > "$$tmp"; test -s "$$tmp"; \
	test -z "$$(nm -u "$$tmp")"; mv "$$tmp" "$@"
build/x86-shootdown-full-cohort.so: build/x86-shootdown-full-cohort.o
	ld -shared -z noexecstack -o "$@" "$<"
build/x86-shootdown-full-cohort-liar.o: tests/negative/x86_shootdown_full_cohort_allow_all.hepta | build check-compiler
	"$(HEPTA_COMPILER)" < "$<" > "$@"
build/x86-shootdown-full-cohort-liar.so: build/x86-shootdown-full-cohort-liar.o
	ld -shared -z noexecstack -o "$@" "$<"
test-x86-shootdown-full-cohort: build/x86-shootdown-full-cohort.so build/x86-shootdown-full-cohort-liar.so
	@set -eu; a=$$(mktemp build/.full-cohort-a.XXXXXX); b=$$(mktemp build/.full-cohort-b.XXXXXX); \
	trap 'rm -f "$$a" "$$b"' EXIT HUP INT TERM; \
	env -i PATH= "$(HEPTA_COMPILER)" < src/x86_shootdown_full_cohort.hepta > "$$a"; \
	env -i PATH= "$(HEPTA_COMPILER)" < src/x86_shootdown_full_cohort.hepta > "$$b"; \
	cmp "$$a" "$$b"; cmp "$$a" build/x86-shootdown-full-cohort.o
	timeout 90 $(PYTHON) tests/test_x86_shootdown_full_cohort.py build/x86-shootdown-full-cohort.so
	$(PYTHON) tests/test_x86_shootdown_full_cohort.py build/x86-shootdown-full-cohort-liar.so --dishonest
test: test-x86-shootdown-full-cohort
