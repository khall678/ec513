#!/usr/bin/env bash

set -euo pipefail

PROJECT="${1:-ec513}"

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
cd "$SCRIPT_DIR"

command -v qsub >/dev/null 2>&1 || { echo "qsub not found in PATH" >&2; exit 1; }
[[ -f build_gem5.qsub ]] || { echo "Missing build_gem5.qsub" >&2; exit 1; }
echo "Submitting build_gem5.qsub first under project $PROJECT..."
BUILD_JOB_ID=$(qsub -terse -P "$PROJECT" build_gem5.qsub | cut -d. -f1)
[[ -n "$BUILD_JOB_ID" ]] || { echo "Failed to capture build job id" >&2; exit 1; }
echo "Build job id: $BUILD_JOB_ID"

echo "Submitting workload jobs with hold_jid=$BUILD_JOB_ID..."
[[ -f 500.perlbench_r.qsub ]] || { echo "Missing 500.perlbench_r.qsub" >&2; exit 1; }
qsub -P "$PROJECT" -hold_jid "$BUILD_JOB_ID" 500.perlbench_r.qsub
[[ -f 502.gcc_r.qsub ]] || { echo "Missing 502.gcc_r.qsub" >&2; exit 1; }
qsub -P "$PROJECT" -hold_jid "$BUILD_JOB_ID" 502.gcc_r.qsub
[[ -f 503.bwaves_r.qsub ]] || { echo "Missing 503.bwaves_r.qsub" >&2; exit 1; }
qsub -P "$PROJECT" -hold_jid "$BUILD_JOB_ID" 503.bwaves_r.qsub
[[ -f 505.mcf_r.qsub ]] || { echo "Missing 505.mcf_r.qsub" >&2; exit 1; }
qsub -P "$PROJECT" -hold_jid "$BUILD_JOB_ID" 505.mcf_r.qsub
[[ -f 507.cactusBSSN_r.qsub ]] || { echo "Missing 507.cactusBSSN_r.qsub" >&2; exit 1; }
qsub -P "$PROJECT" -hold_jid "$BUILD_JOB_ID" 507.cactusBSSN_r.qsub
[[ -f 508.namd_r.qsub ]] || { echo "Missing 508.namd_r.qsub" >&2; exit 1; }
qsub -P "$PROJECT" -hold_jid "$BUILD_JOB_ID" 508.namd_r.qsub
[[ -f 510.parest_r.qsub ]] || { echo "Missing 510.parest_r.qsub" >&2; exit 1; }
qsub -P "$PROJECT" -hold_jid "$BUILD_JOB_ID" 510.parest_r.qsub
[[ -f 511.povray_r.qsub ]] || { echo "Missing 511.povray_r.qsub" >&2; exit 1; }
qsub -P "$PROJECT" -hold_jid "$BUILD_JOB_ID" 511.povray_r.qsub
[[ -f 519.lbm_r.qsub ]] || { echo "Missing 519.lbm_r.qsub" >&2; exit 1; }
qsub -P "$PROJECT" -hold_jid "$BUILD_JOB_ID" 519.lbm_r.qsub
[[ -f 520.omnetpp_r.qsub ]] || { echo "Missing 520.omnetpp_r.qsub" >&2; exit 1; }
qsub -P "$PROJECT" -hold_jid "$BUILD_JOB_ID" 520.omnetpp_r.qsub
[[ -f 521.wrf_r.qsub ]] || { echo "Missing 521.wrf_r.qsub" >&2; exit 1; }
qsub -P "$PROJECT" -hold_jid "$BUILD_JOB_ID" 521.wrf_r.qsub
[[ -f 523.xalancbmk_r.qsub ]] || { echo "Missing 523.xalancbmk_r.qsub" >&2; exit 1; }
qsub -P "$PROJECT" -hold_jid "$BUILD_JOB_ID" 523.xalancbmk_r.qsub
[[ -f 525.x264_r.qsub ]] || { echo "Missing 525.x264_r.qsub" >&2; exit 1; }
qsub -P "$PROJECT" -hold_jid "$BUILD_JOB_ID" 525.x264_r.qsub
[[ -f 527.cam4_r.qsub ]] || { echo "Missing 527.cam4_r.qsub" >&2; exit 1; }
qsub -P "$PROJECT" -hold_jid "$BUILD_JOB_ID" 527.cam4_r.qsub
[[ -f 531.deepsjeng_r.qsub ]] || { echo "Missing 531.deepsjeng_r.qsub" >&2; exit 1; }
qsub -P "$PROJECT" -hold_jid "$BUILD_JOB_ID" 531.deepsjeng_r.qsub
[[ -f 538.imagick_r.qsub ]] || { echo "Missing 538.imagick_r.qsub" >&2; exit 1; }
qsub -P "$PROJECT" -hold_jid "$BUILD_JOB_ID" 538.imagick_r.qsub
[[ -f 541.leela_r.qsub ]] || { echo "Missing 541.leela_r.qsub" >&2; exit 1; }
qsub -P "$PROJECT" -hold_jid "$BUILD_JOB_ID" 541.leela_r.qsub
[[ -f 544.nab_r.qsub ]] || { echo "Missing 544.nab_r.qsub" >&2; exit 1; }
qsub -P "$PROJECT" -hold_jid "$BUILD_JOB_ID" 544.nab_r.qsub
[[ -f 548.exchange2_r.qsub ]] || { echo "Missing 548.exchange2_r.qsub" >&2; exit 1; }
qsub -P "$PROJECT" -hold_jid "$BUILD_JOB_ID" 548.exchange2_r.qsub
[[ -f 557.xz_r.qsub ]] || { echo "Missing 557.xz_r.qsub" >&2; exit 1; }
qsub -P "$PROJECT" -hold_jid "$BUILD_JOB_ID" 557.xz_r.qsub
