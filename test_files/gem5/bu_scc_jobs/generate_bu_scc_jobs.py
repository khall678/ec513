#!/usr/bin/env python3
"""Generate independent BU SCC qsub files for the sample SPEC workloads.

This trims the directory down to the three workloads from submit_sample.sh and
emits one qsub per individual run so SCC can schedule every point
independently.
"""

from pathlib import Path


DEFAULT_PROJECT = "ec513"
JOBS_DIR = Path(__file__).resolve().parent
GEM5_ROOT = JOBS_DIR.parent
PROJECT_ROOT = GEM5_ROOT.parent

SAMPLE_BENCHMARKS = [
    "505.mcf_r",
    "500.perlbench_r",
    "538.imagick_r",
]

CONFIDENCE_TABLE_SIZE = "8192"
LOCALBP_COUNTER_BITS = ["2", "3", "4"]
CAMP_COUNTER_BITS = ["2", "3", "4"]
MLP_PREDICTOR = "MultiperspectivePerceptron64KB"


def safe_name(name: str) -> str:
    return name.replace(".", "_")


def qsub_text(job_name: str, log_name: str, benchmark: str, run_args: list[str]) -> str:
    args_lines = " \\\n".join(f"  {arg}" for arg in run_args)
    return f"""#!/bin/bash -l
#$ -cwd
#$ -V
#$ -j y
#$ -P {DEFAULT_PROJECT}
#$ -N {job_name}
#$ -o logs/{log_name}.$JOB_ID.log
#$ -pe omp 8
#$ -l h_rt=48:00:00

set -euo pipefail

PROJECT_ROOT="{PROJECT_ROOT}"
GEM5_ROOT="{GEM5_ROOT}"

source "$PROJECT_ROOT/sourceme"
cd "$GEM5_ROOT"

./run_project_benchmark.sh \\
  --benchmarks {benchmark} \\
  --warmup-mode timing \\
  --warmup-insts 1000000 \\
  --measure-insts 100000000 \\
  --size ref \\
{args_lines}
"""


def emit_localbp_jobs() -> list[str]:
    files: list[str] = []
    for benchmark in SAMPLE_BENCHMARKS:
        bench_safe = safe_name(benchmark)
        for counter_bits in LOCALBP_COUNTER_BITS:
            run_tag = f"LocalBP_cb{counter_bits}_cts{CONFIDENCE_TABLE_SIZE}"
            job_stem = f"{benchmark}.localbp_cb{counter_bits}"
            text = qsub_text(
                job_name=f"lbp_{bench_safe}_cb{counter_bits}",
                log_name=f"{bench_safe}.localbp_cb{counter_bits}",
                benchmark=benchmark,
                run_args=[
                    "--predictors LocalBP",
                    f"--camp-counter-bits {counter_bits}",
                    f"--confidence-table-sizes {CONFIDENCE_TABLE_SIZE}",
                ],
            )
            path = JOBS_DIR / f"{job_stem}.qsub"
            path.write_text(text, encoding="ascii")
            files.append(path.name)
    return files


def emit_camp_jobs() -> list[str]:
    files: list[str] = []
    for benchmark in SAMPLE_BENCHMARKS:
        bench_safe = safe_name(benchmark)
        for counter_bits in CAMP_COUNTER_BITS:
            job_stem = f"{benchmark}.camp_cb{counter_bits}"
            text = qsub_text(
                job_name=f"camp_{bench_safe}_c{counter_bits}",
                log_name=f"{bench_safe}.camp_cb{counter_bits}",
                benchmark=benchmark,
                run_args=[
                    "--predictors CAMP",
                    f"--camp-counter-bits {counter_bits}",
                    f"--confidence-table-sizes {CONFIDENCE_TABLE_SIZE}",
                ],
            )
            path = JOBS_DIR / f"{job_stem}.qsub"
            path.write_text(text, encoding="ascii")
            files.append(path.name)
    return files


def emit_mlp_jobs() -> list[str]:
    files: list[str] = []
    for benchmark in SAMPLE_BENCHMARKS:
        bench_safe = safe_name(benchmark)
        job_stem = f"{benchmark}.mlp64kb"
        text = qsub_text(
            job_name=f"mlp_{bench_safe}",
            log_name=f"{bench_safe}.mlp64kb",
            benchmark=benchmark,
            run_args=[f"--predictors {MLP_PREDICTOR}"],
        )
        path = JOBS_DIR / f"{job_stem}.qsub"
        path.write_text(text, encoding="ascii")
        files.append(path.name)
    return files


def submit_sample_text(job_files: list[str]) -> str:
    quoted_jobs = "\n".join(f'  "{job}"' for job in job_files)
    return f"""#!/usr/bin/env bash

set -euo pipefail

PROJECT="${{1:-{DEFAULT_PROJECT}}}"

SCRIPT_DIR=$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)
cd "$SCRIPT_DIR"

command -v qsub >/dev/null 2>&1 || {{ echo "qsub not found in PATH" >&2; exit 1; }}

SAMPLE_JOBS=(
{quoted_jobs}
)

for job in "${{SAMPLE_JOBS[@]}}"; do
  [[ -f "$job" ]] || {{ echo "Missing $job" >&2; exit 1; }}
done

echo "Submitting independent sample jobs under project $PROJECT..."
echo "Benchmarks: {", ".join(SAMPLE_BENCHMARKS)}"
echo "LocalBP: counter bits [{", ".join(LOCALBP_COUNTER_BITS)}], cts={CONFIDENCE_TABLE_SIZE}"
echo "CAMP: counter bits [{", ".join(CAMP_COUNTER_BITS)}], cts={CONFIDENCE_TABLE_SIZE}"
echo "MLP baseline: {MLP_PREDICTOR}"
echo "Total jobs: {len(job_files)}"

for job in "${{SAMPLE_JOBS[@]}}"; do
  qsub -P "$PROJECT" "$job"
done
"""


def main() -> None:
    logs_dir = JOBS_DIR / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / ".gitkeep").touch()

    job_files = []
    job_files.extend(emit_localbp_jobs())
    job_files.extend(emit_camp_jobs())
    job_files.extend(emit_mlp_jobs())
    job_files.sort()

    submit_sample = JOBS_DIR / "submit_sample.sh"
    submit_sample.write_text(submit_sample_text(job_files), encoding="ascii")
    submit_sample.chmod(0o755)

    print(f"Generated {len(job_files)} independent sample qsub files.")


if __name__ == "__main__":
    main()
