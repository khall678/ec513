# CAMP Deliverable Bundle

This directory is the handoff bundle that should be pushed to the remote.
It contains only the files needed to install the CAMP project changes into an
existing `spec-2017` tree.

## Assumed Layout

This bundle assumes it was cloned somewhere under an existing parent directory
named `spec-2017`, with the usual project layout already present.

Example:

```text
/your/work/
  spec-2017/
    gem5/
    disk-image/
    sourceme
    your-cloned-bundle/
      test_files/
        setup.sh
        README.md
        ...
```

In that setup, running `test_files/setup.sh` from the cloned bundle will detect
the surrounding `spec-2017` directory and install the bundled files into the
correct locations there.

If auto-detection does not work, you can point it at the target explicitly:

```bash
./test_files/setup.sh --target /path/to/spec-2017
```

By default the installer copies files so the bundle stays intact. If you want
the bundle files moved instead, run:

```bash
./test_files/setup.sh --move
```

## What `setup.sh` Does

`test_files/setup.sh` installs the bundled files into the target `spec-2017`
tree:

- `gem5/src/cpu/pred/camp.cc`
- `gem5/src/cpu/pred/camp.hh`
- `gem5/src/cpu/pred/BranchPredictor.py`
- `gem5/src/cpu/pred/SConscript`
- `gem5/ec513_custom/simulate_CAMP.py`
- `gem5/run_project_benchmark.sh`
- everything in `gem5/bu_scc_jobs/`
- `project_answers.py`
- everything in `project_plot/`

After installing, it prints the next steps to rebuild gem5 and continue using
the project.

## File Guide

### Installer and docs

- `setup.sh`
  Installs the bundle into the surrounding `spec-2017` tree.
- `README.md`
  Explains the bundle layout, assumptions, and what each delivered file does.

### Predictor implementation

- `gem5/src/cpu/pred/camp.cc`
  Main CAMP predictor implementation.
- `gem5/src/cpu/pred/camp.hh`
  CAMP predictor declarations and class interface.
- `gem5/src/cpu/pred/BranchPredictor.py`
  gem5 SimObject definition that exposes predictors (including CAMP) to Python configs.
- `gem5/src/cpu/pred/SConscript`
  gem5 build script for predictor implementations.

### Simulation driver

- `gem5/ec513_custom/simulate_CAMP.py`
  Full-system gem5 driver for boot, warmup, O3 measurement, predictor
  selection, and run metadata output.
- `gem5/run_project_benchmark.sh`
  Batch runner that launches LocalBP, MLP, CAMP, and sweep configurations.

### SCC job files

- `gem5/bu_scc_jobs/build_gem5.qsub`
  SCC job for rebuilding gem5 once.
- `gem5/bu_scc_jobs/*.qsub`
  Per-benchmark SCC jobs that run the project workloads.
- `gem5/bu_scc_jobs/generate_bu_scc_jobs.py`
  Generator script for the `.qsub` files.
- `gem5/bu_scc_jobs/submit_all.sh`
  Convenience wrapper to submit the full SCC campaign.
- `gem5/bu_scc_jobs/submit_sample.sh`
  Convenience wrapper to submit a smaller sample subset.

### Analysis

- `project_answers.py`
  Parses `stats.txt`, chooses the correct measurement core, and generates CSV,
  markdown, and figures.
- `project_plot/summary.csv`
  Extracted metrics for completed runs.
- `project_plot/summary.md`
  Short human-readable summary of the current results.
- `project_plot/fig0_metrics_dashboard.png`
  Concise dashboard showing misprediction rate, fetch/commit ratio, CPI, and
  DRAM power when available.
- `project_plot/fig1_baseline_comparison.png`
  Baseline comparison plot for misprediction rate and CPI.

## After Installation

From the target `spec-2017` tree:

```bash
./setup.sh
source sourceme
cd gem5
scons build/X86/gem5.opt -j $(command -v nproc >/dev/null 2>&1 && nproc || echo 4)
```

Then you can run benchmarks or regenerate plots as usual.
