#!/bin/bash
# run_unit_tests.sh — corre los unit tests .nx (hoy: src/template.nx)
# compilándolos con el bootstrap del toolchain (NYX_HOME). Patrón adoptado
# de nyx-db-stack/scripts/run_unit_tests.sh.
#
# OJO: usa $NYX_HOME/script.nx compartido — NO correr en paralelo con
# suites del monorepo ni de otros stacks (regla preexistente: los runners
# nunca se solapan).
set -uo pipefail
STACK="$(cd "$(dirname "$0")/.." && pwd)"
NYX_HOME="${NYX_HOME:-/home/admin/nyx/lang}"
cd "$STACK"
pass=0; fail=0
for src in tests/*.nx; do
    name="$(basename "$src" .nx)"
    cp "$src" "$NYX_HOME/script.nx"
    if out=$(cd "$NYX_HOME" && NYX_PROJECT_DIR="$STACK" ./nyx_bootstrap >/dev/null 2>&1 && \
             clang -O2 script.ll runtime/*.c runtime/os/os_posix.c -lgc -lpthread -ldl -lm -lssl -lcrypto -lz -o script_bin 2>/dev/null && \
             timeout 60 ./script_bin 2>&1); then
        if echo "$out" | grep -q "ASSERTION FAILED"; then
            echo "FAIL $name (assertion)"
            echo "$out" | tail -5
            fail=$((fail+1))
        else
            echo "ok $name"
            pass=$((pass+1))
        fi
    else
        echo "FAIL $name"
        echo "$out" | tail -20
        fail=$((fail+1))
    fi
    rm -f "$NYX_HOME/script.nx" "$NYX_HOME/script.ll" "$NYX_HOME/script_bin"
done
echo "Suites: $pass ok, $fail fail"
[ "$fail" -eq 0 ]
