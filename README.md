# CAMP Branch Prediction Study

This repository adds a custom `CAMP` branch predictor to gem5, plus a full run-and-analysis workflow for comparing it against baseline bimodal and MLP predictors on SPEC CPU2017 workloads.

`CAMP` here is implemented as:

- A `LocalBP`-style PC-indexed saturating-counter table that supplies the simple bimodal prediction.
- A `MultiperspectivePerceptron64KB` model that supplies the complex prediction.
- A configurable confidence window over the saturating-counter states.
  If the counter is in the centered `mlpWindowStates`, CAMP returns the MLP prediction.
  Otherwise it returns the bimodal prediction.

## What Changed

### gem5 predictor integration

- Added a real CAMP implementation in `gem5/src/cpu/pred/camp.cc` and `gem5/src/cpu/pred/camp.hh`.
- Exposed predictors (including CAMP) to Python configs in `gem5/src/cpu/pred/BranchPredictor.py`.
- Hooked up CAMP to the gem5 build system via `gem5/src/cpu/pred/SConscript`.
- CAMP parameters are now configurable:
  - `confidenceTableSize`: total counter-table size in bits.
  - `counterBits`: saturating-counter width.
  - `mlpWindowStates`: number of centered states that consult the MLP.

Implementation note:

- gem5's stock `LocalBP` does not expose raw counter values.
  To preserve the existing bimodal predictor while still making confidence-window decisions, CAMP mirrors a matching saturating-counter table internally for confidence selection.

### Simulation and benchmark workflow

- Reworked `gem5/ec513_custom/simulate_CAMP.py` into a reusable driver for:
  - `LocalBP`
  - `MultiperspectivePerceptron64KB`
  - `CAMP`
  - optional legacy predictors (`TournamentBP`, `LTAGE`, `MultiperspectivePerceptronTAGE64KB`)
- The simulation now:
  - boots with KVM,
  - warms on `TimingSimpleCPU` by default for speed and SCC compatibility,
  - can fall back from blocked KVM warmup requests to `TimingSimpleCPU`,
  - can optionally warm on O3 for higher fidelity,
  - switches to O3,
  - measures `100M` instructions by default,
  - writes `run_metadata.json` into each `m5out` run directory.

- Replaced `gem5/run_project_benchmark.sh` with a configurable sweep driver.
  It can sweep:
  - workloads,
  - `LocalBP` counter widths,
  - `CAMP` counter widths,
  - `CAMP` confidence-window sizes.

### BU SCC job support

- Added `gem5/bu_scc_jobs/generate_bu_scc_jobs.py`.
- Generated one `.qsub` file per SPEC workload in `gem5/bu_scc_jobs/`.
- Added:
  - `build_gem5.qsub` for rebuilding gem5 once on SCC,
  - `submit_all.sh` to submit the full campaign.

Each workload qsub runs a single benchmark and writes outputs under `gem5/m5out/<benchmark>/<run_name>/`.

### Analysis and plots

- Added `project_answers.py` to parse `stats.txt` files under `gem5/m5out/`.
- The script extracts:
  - conditional branch misprediction rate,
  - fetch/commit ratio,
  - CPI,
  - DRAM power if gem5 emitted it.
- Outputs go to `project_plot/`:
  - `summary.csv`
  - `summary.md`
  - grouped bar charts for CAMP vs baselines across workloads
  - CAMP parameter-sweep bar charts across workloads

## Quick Setup

```bash
./setup.sh
source sourceme
```

The setup script creates a local virtual environment and installs the Python packages needed for plotting and for gem5's Python-side tooling.
`source sourceme` loads the required SCC modules and activates the repository virtual environment.
If you are not on SCC, `sourceme` will skip the module loads and still try to activate the local virtualenv.

## Make This A Branch On `khall678/ec513` Without Fetching First

If you want this current directory to become your work on top of `https://github.com/khall678/ec513` without first pulling that repo into the tree, use:

```bash
git init
git add .
git commit -m "Add CAMP branch prediction study workflow"
git remote add upstream https://github.com/khall678/ec513.git
git push upstream HEAD:your-branch-name
```

That push creates `your-branch-name` on the remote from your current commit history as-is.
It does not fetch or merge the remote's existing contents into this directory first.
If the remote rejects the push because histories are unrelated or the branch name already exists, create a fresh branch name and push again.

## Build gem5

```bash
cd gem5
source ../sourceme
scons build/X86/gem5.opt -j $(nproc)
```

Rebuild after editing the CAMP predictor or its SimObject definition.

## Run Benchmarks Locally

From `gem5/`:

```bash
source ../sourceme
./run_project_benchmark.sh --help
```

Typical single-workload example:

```bash
./run_project_benchmark.sh \
  --benchmarks 505.mcf_r \
  --predictors LocalBP,MultiperspectivePerceptron64KB,CAMP \
  --camp-counter-bits 2,3,4 \
  --camp-window-states 2,4 \
  --confidence-table-size 8192 \
  --warmup-mode timing \
  --warmup-insts 1000000 \
  --measure-insts 100000000 \
  --size ref
```

Useful options:

- `--benchmarks smoke`
  Runs a small local smoke set.
- `--benchmarks all`
  Runs all 20 SPEC workloads.
- `--warmup-mode timing`
  Safe default on SCC. Boot happens on KVM, warmup on `TimingSimpleCPU`, then the measured window runs on O3.
- `--warmup-mode kvm`
  Only use this on hosts where KVM perf counters are allowed; otherwise the script falls back to `timing`.
- `--warmup-mode o3`
  Slower, but warms the detailed O3 predictor state before measurement.
- `--rebuild`
  Rebuilds gem5 before starting the batch.

## Run on Boston University SCC

To run your jobs on the BU SCC cluster, navigate to the jobs directory:

```bash
cd gem5/bu_scc_jobs/
```

**1. Build gem5 First**
Submit the initial job to compile gem5:
```bash
qsub -P ec513 build_gem5.qsub
```
Wait for this job to finish successfully before proceeding to step 2.

**2. Run Benchmarks**
Once built, you can submit a specific workload:
```bash
qsub -P ec513 505.mcf_r.qsub
```
Or use the convenience script to submit the entire campaign at once:
```bash
./submit_all.sh
```

*(Note: Adjust `-P ec513` to match your specific SCC project code if it differs.)*

## Generate Plots

From the repository root:

```bash
python project_answers.py
```

Optional custom locations:

```bash
python project_answers.py --m5out-root gem5/m5out --plot-dir project_plot
```

## Expected Output Layout

Each run lands in a directory like:

```text
gem5/m5out/505.mcf_r/CAMP_cb2_ws2_cts8192/
```

and contains:

- `stats.txt`
- `config.ini`
- `config.json`
- `run_metadata.json`

## Recommended Study

To analyze the effect of CAMP sizing:

1. Run `LocalBP` with matching counter widths.
2. Run `MultiperspectivePerceptron64KB` as the MLP baseline.
3. Sweep CAMP over:
   - `counterBits = 2, 3, 4`
   - `mlpWindowStates = 2, 4`
4. Compare:
   - misprediction rate,
   - fetch/commit ratio,
   - CPI,
   - DRAM power if present.

## Files to Know

- `gem5/src/cpu/pred/camp.cc`
- `gem5/src/cpu/pred/camp.hh`
- `gem5/src/cpu/pred/BranchPredictor.py`
- `gem5/src/cpu/pred/SConscript`
- `gem5/ec513_custom/simulate_CAMP.py`
- `gem5/run_project_benchmark.sh`
- `gem5/bu_scc_jobs/`
- `project_answers.py`
- `project_plot/`
