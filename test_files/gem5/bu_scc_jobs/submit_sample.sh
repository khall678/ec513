#!/usr/bin/env bash

set -euo pipefail

PROJECT="${1:-ec513}"

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR"

command -v qsub >/dev/null 2>&1 || { echo "qsub not found in PATH" >&2; exit 1; }

SAMPLE_JOBS=(
  "500.perlbench_r.camp_cb2.qsub"
  "500.perlbench_r.camp_cb3.qsub"
  "500.perlbench_r.camp_cb4.qsub"
  "500.perlbench_r.localbp_cb2.qsub"
  "500.perlbench_r.localbp_cb3.qsub"
  "500.perlbench_r.localbp_cb4.qsub"
  "500.perlbench_r.mlp64kb.qsub"
  "505.mcf_r.camp_cb2.qsub"
  "505.mcf_r.camp_cb3.qsub"
  "505.mcf_r.camp_cb4.qsub"
  "505.mcf_r.localbp_cb2.qsub"
  "505.mcf_r.localbp_cb3.qsub"
  "505.mcf_r.localbp_cb4.qsub"
  "505.mcf_r.mlp64kb.qsub"
  "538.imagick_r.camp_cb2.qsub"
  "538.imagick_r.camp_cb3.qsub"
  "538.imagick_r.camp_cb4.qsub"
  "538.imagick_r.localbp_cb2.qsub"
  "538.imagick_r.localbp_cb3.qsub"
  "538.imagick_r.localbp_cb4.qsub"
  "538.imagick_r.mlp64kb.qsub"
)

for job in "${SAMPLE_JOBS[@]}"; do
  [[ -f "$job" ]] || { echo "Missing $job" >&2; exit 1; }
done

echo "Submitting independent sample jobs under project $PROJECT..."
echo "Benchmarks: 505.mcf_r, 500.perlbench_r, 538.imagick_r"
echo "LocalBP: counter bits [2, 3, 4], cts=8192"
echo "CAMP: counter bits [2, 3, 4], cts=8192"
echo "MLP baseline: MultiperspectivePerceptron64KB"
echo "Total jobs: 21"

for job in "${SAMPLE_JOBS[@]}"; do
  qsub -P "$PROJECT" "$job"
done
