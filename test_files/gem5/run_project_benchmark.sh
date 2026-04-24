#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
SOURCE_ME="$PROJECT_ROOT/sourceme"
SIM_SCRIPT="ec513_custom/simulate_CAMP.py"
GEM5_BIN="$SCRIPT_DIR/build/X86/gem5.opt"
DISK_IMAGE_DEFAULT="$PROJECT_ROOT/disk-image/spec-2017/spec-2017-image/spec-2017"
OUT_ROOT="$SCRIPT_DIR/m5out"

ALL_BENCHMARKS=(
    "500.perlbench_r"
    "502.gcc_r"
    "503.bwaves_r"
    "505.mcf_r"
    "507.cactusBSSN_r"
    "508.namd_r"
    "510.parest_r"
    "511.povray_r"
    "519.lbm_r"
    "520.omnetpp_r"
    "521.wrf_r"
    "523.xalancbmk_r"
    "525.x264_r"
    "527.cam4_r"
    "531.deepsjeng_r"
    "538.imagick_r"
    "541.leela_r"
    "544.nab_r"
    "548.exchange2_r"
    "557.xz_r"
)

SMOKE_BENCHMARKS=(
    "505.mcf_r"
    "500.perlbench_r"
    "502.gcc_r"
)

BENCHMARKS=("505.mcf_r")
PREDICTORS=("LocalBP" "MultiperspectivePerceptron64KB" "CAMP")
CAMP_COUNTER_BITS=("2")
CAMP_WINDOW_STATES=("2")
# Comma-separated list of table sizes to sweep; each size runs its own CAMP
# (and LocalBP) experiment.  Default is a single value for backward compat.
CONFIDENCE_TABLE_SIZES=("8192")
PARTITION=1
SIZE="test"
WARMUP_INSTS=1000000
WARMUP_MODE="timing"
MEASURE_INSTS=100000000
DISK_IMAGE="$DISK_IMAGE_DEFAULT"
BUILD_JOBS="${BUILD_JOBS:-$(command -v nproc >/dev/null 2>&1 && nproc || echo 4)}"
REBUILD=0
DRY_RUN=0
SKIP_SOURCE=0

print_usage() {
    cat <<'EOF'
Usage: ./run_project_benchmark.sh [options]

Options:
  --benchmarks VALUE              Comma list, "smoke", or "all"
  --predictors VALUE              Comma list of:
                                    LocalBP, TournamentBP, LTAGE,
                                    MultiperspectivePerceptron64KB,
                                    MultiperspectivePerceptronTAGE64KB, CAMP
  --camp-counter-bits VALUE       Comma list of CAMP/LocalBP counter sizes
  --confidence-table-size VALUE   Single table size in bits (LocalBP/CAMP)
  --confidence-table-sizes VALUE  Comma list of table sizes to sweep (LocalBP/CAMP)
  --warmup-insts VALUE            Warmup instructions before measurement
  --warmup-mode VALUE             Warmup core type: timing, kvm, or o3
  --measure-insts VALUE           Measurement instructions on O3
  --size VALUE                    SPEC size: test/train/ref
  --image VALUE                   Full path to disk image
  --partition VALUE               Disk partition
  --gem5-bin VALUE                Path to gem5.opt
  --out-root VALUE                Root output directory
  --build-jobs VALUE              Parallelism for scons rebuild
  --skip-source                   Do not source ../sourceme before running
  --rebuild                       Rebuild gem5 before launching runs
  --dry-run                       Print commands without running them
  --help                          Show this help
EOF
}

split_csv() {
    local input="$1"
    local -n out_ref=$2
    IFS=',' read -r -a out_ref <<< "$input"
}

resolve_benchmarks() {
    local selector="$1"
    case "$selector" in
        all)
            BENCHMARKS=("${ALL_BENCHMARKS[@]}")
            ;;
        smoke)
            BENCHMARKS=("${SMOKE_BENCHMARKS[@]}")
            ;;
        *)
            split_csv "$selector" BENCHMARKS
            ;;
    esac
}

build_if_requested() {
    if [[ "$REBUILD" -eq 0 ]]; then
        return
    fi

    echo "Rebuilding gem5 with scons..."
    (
        cd "$SCRIPT_DIR"
        scons build/X86/gem5.opt -j "$BUILD_JOBS"
    )
}

source_env_if_requested() {
    if [[ "$SKIP_SOURCE" -eq 1 ]]; then
        return
    fi

    if [[ ! -f "$SOURCE_ME" ]]; then
        echo "Expected environment file not found: $SOURCE_ME" >&2
        exit 1
    fi

    # shellcheck disable=SC1090
    source "$SOURCE_ME"
}

run_cmd() {
    if [[ "$DRY_RUN" -eq 1 ]]; then
        printf '%q ' "$@"
        printf '\n'
        return
    fi
    "$@"
}

validate_run_output() {
    local outdir="$1"
    local stats_file="$outdir/stats.txt"
    local metadata_file="$outdir/run_metadata.json"
    local status_file="$outdir/run_status.json"

    if [[ ! -s "$stats_file" ]]; then
        echo "Run failed: stats file is missing or empty: $stats_file" >&2
        [[ -f "$status_file" ]] && echo "Status file: $status_file" >&2
        [[ -f "$outdir/run_error.txt" ]] && echo "Error file: $outdir/run_error.txt" >&2
        return 1
    fi

    if [[ ! -f "$metadata_file" ]]; then
        echo "Run failed: metadata file was not created: $metadata_file" >&2
        [[ -f "$status_file" ]] && echo "Status file: $status_file" >&2
        [[ -f "$outdir/run_error.txt" ]] && echo "Error file: $outdir/run_error.txt" >&2
        return 1
    fi
}

run_benchmark() {
    local benchmark="$1"
    local run_name="$2"
    shift 2

    local outdir="$OUT_ROOT/$benchmark/$run_name"
    mkdir -p "$outdir"
    local run_log="$outdir/gem5_run.log"

    echo "Starting $benchmark -> $run_name"
    if [[ "$DRY_RUN" -eq 1 ]]; then
        run_cmd "$GEM5_BIN" -d "$outdir" \
            "$SIM_SCRIPT" \
            --image "$DISK_IMAGE" \
            --partition "$PARTITION" \
            --benchmark "$benchmark" \
            --size "$SIZE" \
            --warmup-insts "$WARMUP_INSTS" \
            --warmup-mode "$WARMUP_MODE" \
            --measure-insts "$MEASURE_INSTS" \
            "$@"
    else
        "$GEM5_BIN" -d "$outdir" \
            "$SIM_SCRIPT" \
            --image "$DISK_IMAGE" \
            --partition "$PARTITION" \
            --benchmark "$benchmark" \
            --size "$SIZE" \
            --warmup-insts "$WARMUP_INSTS" \
            --warmup-mode "$WARMUP_MODE" \
            --measure-insts "$MEASURE_INSTS" \
            "$@" 2>&1 | tee "$run_log"
        local gem5_status=${PIPESTATUS[0]}
        if [[ "$gem5_status" -ne 0 ]]; then
            echo "gem5 exited with status $gem5_status for $benchmark -> $run_name" >&2
            exit "$gem5_status"
        fi
        validate_run_output "$outdir"
    fi
    echo "Finished $benchmark -> $run_name"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --benchmarks)
            resolve_benchmarks "$2"
            shift 2
            ;;
        --predictors)
            split_csv "$2" PREDICTORS
            shift 2
            ;;
        --camp-counter-bits)
            split_csv "$2" CAMP_COUNTER_BITS
            shift 2
            ;;

        # Accept both singular and plural forms; plural takes precedence.
        --confidence-table-size)
            CONFIDENCE_TABLE_SIZES=("$2")
            shift 2
            ;;
        --confidence-table-sizes)
            split_csv "$2" CONFIDENCE_TABLE_SIZES
            shift 2
            ;;
        --warmup-insts)
            WARMUP_INSTS="$2"
            shift 2
            ;;
        --warmup-mode)
            WARMUP_MODE="$2"
            shift 2
            ;;
        --measure-insts)
            MEASURE_INSTS="$2"
            shift 2
            ;;
        --size)
            SIZE="$2"
            shift 2
            ;;
        --image)
            DISK_IMAGE="$2"
            shift 2
            ;;
        --partition)
            PARTITION="$2"
            shift 2
            ;;
        --gem5-bin)
            GEM5_BIN="$2"
            shift 2
            ;;
        --out-root)
            OUT_ROOT="$2"
            shift 2
            ;;
        --build-jobs)
            BUILD_JOBS="$2"
            shift 2
            ;;
        --skip-source)
            SKIP_SOURCE=1
            shift
            ;;
        --rebuild)
            REBUILD=1
            shift
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        --help)
            print_usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            print_usage
            exit 1
            ;;
    esac
done

source_env_if_requested
mkdir -p "$OUT_ROOT"
build_if_requested

for benchmark in "${BENCHMARKS[@]}"; do
    for predictor in "${PREDICTORS[@]}"; do
        case "$predictor" in
            LocalBP)
                for counter_bits in "${CAMP_COUNTER_BITS[@]}"; do
                    for table_size in "${CONFIDENCE_TABLE_SIZES[@]}"; do
                        run_name="LocalBP_cb${counter_bits}_cts${table_size}"
                        run_benchmark "$benchmark" "$run_name" \
                            --predictor LocalBP \
                            --counter-bits "$counter_bits" \
                            --confidence-table-size "$table_size" \
                            --run-tag "$run_name"
                    done
                done
                ;;
            TournamentBP)
                run_name="TournamentBP"
                run_benchmark "$benchmark" "$run_name" \
                    --predictor TournamentBP \
                    --run-tag "$run_name"
                ;;
            LTAGE)
                run_name="LTAGE"
                run_benchmark "$benchmark" "$run_name" \
                    --predictor LTAGE \
                    --run-tag "$run_name"
                ;;
            MultiperspectivePerceptron64KB)
                run_name="MultiperspectivePerceptron64KB"
                run_benchmark "$benchmark" "$run_name" \
                    --predictor MultiperspectivePerceptron64KB \
                    --run-tag "$run_name"
                ;;
            MultiperspectivePerceptronTAGE64KB)
                run_name="MultiperspectivePerceptronTAGE64KB"
                run_benchmark "$benchmark" "$run_name" \
                    --predictor MultiperspectivePerceptronTAGE64KB \
                    --run-tag "$run_name"
                ;;
            CAMP)
                for counter_bits in "${CAMP_COUNTER_BITS[@]}"; do
                    for table_size in "${CONFIDENCE_TABLE_SIZES[@]}"; do
                        run_name="CAMP_cb${counter_bits}_cts${table_size}"
                        run_benchmark "$benchmark" "$run_name" \
                            --predictor CAMP \
                            --counter-bits "$counter_bits" \
                            --confidence-table-size "$table_size" \
                            --run-tag "$run_name"
                    done
                done
                ;;
            *)
                echo "Unsupported predictor: $predictor" >&2
                exit 1
                ;;
        esac
    done
done
