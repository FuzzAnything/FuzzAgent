#!/usr/bin/env bash
set -uo pipefail

BENCHMARK_DURATION="${FUZZING_DURATION:-24h}"
echo "Starting FuzzAgent benchmark for $BENCHMARK_DURATION."
timeout --signal=INT --kill-after=60s "$BENCHMARK_DURATION" uv run main.py
FUZZ_EXIT_CODE=$?

if [[ "$FUZZ_EXIT_CODE" -ne 0 && "$FUZZ_EXIT_CODE" -ne 124 ]]; then
    echo "FuzzAgent exited with status $FUZZ_EXIT_CODE; skipping final coverage export." >&2
    exit "$FUZZ_EXIT_CODE"
fi

echo "Benchmark complete. Exporting full code coverage."
bash /root/FuzzAgent/src/tools/copy_tools.sh
exec python3 -m introspector
