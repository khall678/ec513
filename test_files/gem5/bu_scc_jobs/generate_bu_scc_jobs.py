#!/usr/bin/env python3
"""Generate BU SCC qsub files for the CAMP branch-predictor study.

Each benchmark gets one qsub job that sweeps ALL CAMP parameters and runs
all baseline predictors in a single job array.  Re-run this script any time
the sweep configuration changes; it overwrites the generated files.
"""

from pathlib import Path


BENCHMARKS = [
    "500.perlbench_r",
    "502.gcc_r",
    "503.bwaves_r",
    "505.mcf_r",
    "507.cactusBSSN_r",
    "508.namd_r",
    "510.parest_r",
    "511.povray_r",
    "519.lbm_r",
    "520.omnetpp_r",
    "521.wrf_r",
    "523.xalancbmk_r",
    "525.x264_r",
    "527.cam4_r",
    "531.deepsjeng_r",
    "538.imagick_r",
    "541.leela_r",
    "544.nab_r",
    "548.exchange2_r",
    "557.xz_r",
]

# ---------------------------------------------------------------------------
# Full parameter sweep
# ---------------------------------------------------------------------------
# Baselines run once each; they are independent of table-size / counter-bits.
BASELINE_PREDICTORS = (
    "LocalBP,"
    "MultiperspectivePerceptron64KB,"
    "LTAGE,"
    "MultiperspectivePerceptronTAGE64KB,"
    "CAMP"
)

# Each axis is swept independently; the other two are held at their defaults
# (counterBits=2, mlpWindowStates=2, confidenceTableSize=8192) when not the
# varied axis.  Having all three in the comma list runs the full product sweep
# in a single job.
CAMP_COUNTER_BITS  = "1,2,3,4"          # vary counter bits   (ws=2, cts=8192)
CAMP_WINDOW_STATES = "1,2,4"            # vary window states  (cb=2, cts=8192)
CONFIDENCE_TABLE_SIZES = "4096,8192,16384"   # vary table size     (cb=2, ws=2)

DEFAULT_PROJECT = "ec513"
JOBS_DIR = Path(__file__).resolve().parent
GEM5_ROOT = JOBS_DIR.parent
PROJECT_ROOT = GEM5_ROOT.parent


def workload_job_text(benchmark: str) -> str:
    safe_name = benchmark.replace(".", "_")
    return f"""#!/bin/bash -l
#$ -cwd
#$ -V
#$ -j y
#$ -P {DEFAULT_PROJECT}
#$ -N camp_{safe_name}
#$ -o logs/{safe_name}.$JOB_ID.log
#$ -pe omp 8
#$ -l h_rt=48:00:00

set -euo pipefail

PROJECT_ROOT="{PROJECT_ROOT}"
GEM5_ROOT="{GEM5_ROOT}"

source "$PROJECT_ROOT/sourceme"
cd "$GEM5_ROOT"

./run_project_benchmark.sh \\
  --benchmarks {benchmark} \\
  --predictors {BASELINE_PREDICTORS} \\
  --camp-counter-bits {CAMP_COUNTER_BITS} \\
  --camp-window-states {CAMP_WINDOW_STATES} \\
  --confidence-table-sizes {CONFIDENCE_TABLE_SIZES} \\
  --warmup-mode timing \\
  --warmup-insts 1000000 \\
  --measure-insts 100000000 \\
  --size ref
"""


def build_job_text() -> str:
    return f"""#!/bin/bash -l
#$ -cwd
#$ -V
#$ -j y
#$ -P ec513
#$ -N gem5_build_camp
#$ -o logs/gem5_build.$JOB_ID.log
#$ -pe omp 8
#$ -l h_rt=12:00:00

set -euo pipefail

PROJECT_ROOT="{PROJECT_ROOT}"
GEM5_ROOT="{GEM5_ROOT}"

source "$PROJECT_ROOT/sourceme"
cd "$GEM5_ROOT"
scons build/X86/gem5.opt -j 8
"""


def submit_all_text() -> str:
    lines = [
        "#!/usr/bin/env bash",
        "",
        "set -euo pipefail",
        "",
        'PROJECT="${1:-ec513}"',
        "",
        'SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)',
        'cd "$SCRIPT_DIR"',
        "",
        'command -v qsub >/dev/null 2>&1 || { echo "qsub not found in PATH" >&2; exit 1; }',
        '[[ -f build_gem5.qsub ]] || { echo "Missing build_gem5.qsub" >&2; exit 1; }',
        'echo "Submitting build_gem5.qsub first under project $PROJECT..."',
        'BUILD_JOB_ID=$(qsub -terse -P "$PROJECT" build_gem5.qsub | cut -d. -f1)',
        '[[ -n "$BUILD_JOB_ID" ]] || { echo "Failed to capture build job id" >&2; exit 1; }',
        'echo "Build job id: $BUILD_JOB_ID"',
        "",
        'echo "Submitting workload jobs with hold_jid=$BUILD_JOB_ID..."',
    ]
    for benchmark in BENCHMARKS:
        lines.append(f'[[ -f {benchmark}.qsub ]] || {{ echo "Missing {benchmark}.qsub" >&2; exit 1; }}')
        lines.append(f'qsub -P "$PROJECT" -hold_jid "$BUILD_JOB_ID" {benchmark}.qsub')
    lines.append("")
    return "\n".join(lines)


# Sample: three representative benchmarks that together cover integer, FP, and
# memory-intensive workloads — good for a quick end-to-end data-collection run.
SAMPLE_BENCHMARKS = ["505.mcf_r", "500.perlbench_r", "538.imagick_r"]


def submit_sample_text() -> str:
    lines = [
        "#!/usr/bin/env bash",
        "",
        "set -euo pipefail",
        "",
        'PROJECT="${1:-ec513}"',
        "",
        'SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)',
        'cd "$SCRIPT_DIR"',
        "",
        'command -v qsub >/dev/null 2>&1 || { echo "qsub not found in PATH" >&2; exit 1; }',
        '[[ -f build_gem5.qsub ]] || { echo "Missing build_gem5.qsub" >&2; exit 1; }',
        'SAMPLE_JOBS=(' + " ".join(f'"{benchmark}.qsub"' for benchmark in SAMPLE_BENCHMARKS) + ')',
        'for job in "${SAMPLE_JOBS[@]}"; do',
        '  [[ -f "$job" ]] || { echo "Missing $job" >&2; exit 1; }',
        'done',
        "",
        'echo "Submitting sample CAMP sweep under project $PROJECT..."',
        'echo "Benchmarks: ' + ", ".join(SAMPLE_BENCHMARKS) + '"',
        'BUILD_JOB_ID=$(qsub -terse -P "$PROJECT" build_gem5.qsub | cut -d. -f1)',
        '[[ -n "$BUILD_JOB_ID" ]] || { echo "Failed to capture build job id" >&2; exit 1; }',
        'echo "Build job id: $BUILD_JOB_ID"',
    ]
    for benchmark in SAMPLE_BENCHMARKS:
        lines.append(f'qsub -P "$PROJECT" -hold_jid "$BUILD_JOB_ID" {benchmark}.qsub')
    lines.append("")
    return "\n".join(lines)


def main():
    jobs_dir = JOBS_DIR
    logs_dir = jobs_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / ".gitkeep").touch()

    (jobs_dir / "build_gem5.qsub").write_text(build_job_text(), encoding="ascii")

    for benchmark in BENCHMARKS:
        (jobs_dir / f"{benchmark}.qsub").write_text(
            workload_job_text(benchmark),
            encoding="ascii",
        )

    submit_all = jobs_dir / "submit_all.sh"
    submit_all.write_text(submit_all_text(), encoding="ascii")
    submit_all.chmod(0o755)

    submit_sample = jobs_dir / "submit_sample.sh"
    submit_sample.write_text(submit_sample_text(), encoding="ascii")
    submit_sample.chmod(0o755)

    print(f"Generated {len(BENCHMARKS)} workload qsub files.")
    print(f"Sample submission covers: {', '.join(SAMPLE_BENCHMARKS)}")
    print(
        f"CAMP sweep: cb=[{CAMP_COUNTER_BITS}]  ws=[{CAMP_WINDOW_STATES}]  "
        f"cts=[{CONFIDENCE_TABLE_SIZES}]"
    )


if __name__ == "__main__":
    main()
