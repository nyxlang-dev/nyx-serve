# Makefile — nyx-serve-stack
# El toolchain Nyx vive fuera de este repo; se apunta vía NYX_HOME.

NYX_HOME ?= /home/admin/nyx/lang
export NYX_HOME

.PHONY: build test-serve test-template clean

build:
	nyx build

# Unit tests .nx (hoy: src/template.nx) — compilados+corridos directo con
# el bootstrap del toolchain (mismo patrón que nyx-db-stack), porque
# `nyx <file.nx>` no resuelve imports de proyecto ("src/...") y `nyx build`
# solo compila el `main` de nyx.toml (examples/standalone.nx) — no hay
# target de PM para correr un .nx de tests/ suelto.
test-template:
	bash scripts/run_unit_tests.sh

# Smoke test HTTP: compila la lib vía examples/standalone.nx y verifica
# rutas, 404 y keep-alive contra un daemon efímero. Agrupa también los
# unit tests .nx (test-template) para que `make test-serve` sea el único
# gate que hay que correr antes de commitear en este repo.
test-serve: build test-template
	python3 tests/test_serve_smoke.py

clean:
	rm -f nyx-serve script.nx script.ll nyx.lock
