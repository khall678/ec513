#!/usr/bin/env bash

set -euo pipefail

PROJECT="${1:-ec513}"

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR"

command -v qsub >/dev/null 2>&1 || { echo "qsub not found in PATH" >&2; exit 1; }
[[ -f build_gem5.qsub ]] || { echo "Missing build_gem5.qsub" >&2; exit 1; }
SAMPLE_JOBS=("505.mcf_r.qsub" "500.perlbench_r.qsub" "538.imagick_r.qsub")
for job in "${SAMPLE_JOBS[@]}"; do
  [[ -f "$job" ]] || { echo "Missing $job" >&2; exit 1; }
done

echo "Submitting sample CAMP sweep under project $PROJECT..."
echo "Benchmarks: 505.mcf_r, 500.perlbench_r, 538.imagick_r"
BUILD_JOB_ID=$(qsub -terse -P "$PROJECT" build_gem5.qsub | cut -d. -f1)
[[ -n "$BUILD_JOB_ID" ]] || { echo "Failed to capture build job id" >&2; exit 1; }
echo "Build job id: $BUILD_JOB_ID"
qsub -P "$PROJECT" -hold_jid "$BUILD_JOB_ID" 505.mcf_r.qsub
qsub -P "$PROJECT" -hold_jid "$BUILD_JOB_ID" 500.perlbench_r.qsub
qsub -P "$PROJECT" -hold_jid "$BUILD_JOB_ID" 538.imagick_r.qsub
