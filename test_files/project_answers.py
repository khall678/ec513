#!/usr/bin/env python3
"""Parse gem5 stats.txt outputs and produce concise CAMP comparison plots.

Five figures are produced:

  fig0_metrics_dashboard.png     – mispred / fetch-commit / CPI / DRAM power
                                   for baselines and CAMP(default)
  fig1_baseline_comparison.png   – mispred rate & CPI: LocalBP / MLP /
                                   LTAGE / MLP-TAGE / CAMP(default)
  fig2_table_size_sweep.png      – CAMP: vary confidenceTableSize
  fig3_counter_window_heatmap.png – CAMP: counter bits vs. window states

For sweep figures, unspecified CAMP axes are held at their defaults
(counterBits=2, mlpWindowStates=2, confidenceTableSize=8192).
"""

import argparse
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern, Tuple

os.environ.setdefault(
    "MPLCONFIGDIR",
    str((Path(__file__).resolve().parent / ".matplotlib").resolve()),
)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Default CAMP axis values (held fixed when another axis is swept)
# ---------------------------------------------------------------------------
DEFAULT_COUNTER_BITS   = 2
DEFAULT_WINDOW_STATES  = 2
DEFAULT_TABLE_SIZE     = 8192

# ---------------------------------------------------------------------------
# gem5 stat patterns
# ---------------------------------------------------------------------------
STAT_PATTERN = re.compile(
    r"^(\S+)\s+([-+]?nan|[-+]?inf|[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)"
)
MEASUREMENT_COMMIT_PATTERN = re.compile(
    r"^(?P<prefix>board\.processor\.(?P<phase>measure|switch)(?P<core>\d+)\.core)"
    r"\.commitStats0\.(?P<stat>numInsts|numInstsNotNOP)$"
)
MEASUREMENT_STAT_SUFFIXES = {
    "cond_predicted": ("branchPred.condPredicted",),
    "cond_incorrect": ("branchPred.condIncorrect",),
    "fetched_insts": ("fetchStats0.numInsts",),
    "committed_insts": ("commitStats0.numInsts", "commitStats0.numInstsNotNOP"),
    "cycles": ("numCycles",),
}
MEASUREMENT_PHASE_PRIORITY = {
    "measure": 0,
    "switch": 1,
}
DRAM_POWER_PATTERN = re.compile(
    r"^board\.memory\.mem_ctrl\d+\.dram\.rank\d+\.averagePower$"
)
RUN_NAME_CAMP  = re.compile(r"^CAMP_cb(?P<bits>\d+)_ws(?P<window>\d+)_cts(?P<size>\d+)$")
RUN_NAME_LOCAL = re.compile(r"^LocalBP_cb(?P<bits>\d+)_cts(?P<size>\d+)$")

# Canonical short labels for the baseline comparison figure
BASELINE_LABEL_MAP = {
    "LocalBP":                         "LocalBP",
    "MultiperspectivePerceptron64KB":   "MLP",
    "LTAGE":                           "LTAGE",
    "MultiperspectivePerceptronTAGE64KB": "MLP-TAGE",
    "TournamentBP":                    "Tournament",
    "CAMP":                            "CAMP(def)",  # default params
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Parse gem5 stats.txt outputs and generate CAMP comparison plots."
    )
    parser.add_argument(
        "--m5out-root",
        default="gem5/m5out",
        help="Path to the gem5 m5out directory.",
    )
    parser.add_argument(
        "--plot-dir",
        default="project_plot",
        help="Directory where plots and summaries should be written.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_stats(stats_path):
    stats = {}
    with stats_path.open("r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            m = STAT_PATTERN.match(line.strip())
            if not m:
                continue
            key, val = m.groups()
            try:
                stats[key] = float(val)
            except ValueError:
                pass
    return stats


def sum_matching(stats, pattern):
    return sum(v for k, v in stats.items() if pattern.match(k))


def get_prefixed_stat(stats, prefix, suffixes):
    for suffix in suffixes:
        key = f"{prefix}.{suffix}"
        if key in stats:
            return stats[key]
    return math.nan


def select_measurement_core(stats, metadata):
    candidates = {}

    for key, value in stats.items():
        match = MEASUREMENT_COMMIT_PATTERN.match(key)
        if not match or value <= 0:
            continue

        prefix = match.group("prefix")
        stat_name = match.group("stat")
        entry = candidates.setdefault(
            prefix,
            {
                "prefix": prefix,
                "phase": match.group("phase"),
                "core_index": int(match.group("core")),
                "committed_insts": value,
            },
        )

        # Prefer the plain committed-instruction stat when gem5 emits both.
        if stat_name == "numInsts" or entry["committed_insts"] <= 0:
            entry["committed_insts"] = value

    if not candidates:
        return {}

    target = metadata.get("measure_insts", math.nan)
    try:
        target = float(target)
    except (TypeError, ValueError):
        target = math.nan

    phase_rank = min(
        MEASUREMENT_PHASE_PRIORITY.get(candidate["phase"], 99)
        for candidate in candidates.values()
    )
    filtered = [
        candidate
        for candidate in candidates.values()
        if MEASUREMENT_PHASE_PRIORITY.get(candidate["phase"], 99) == phase_rank
    ]

    def sort_key(candidate):
        core_index = int(candidate["core_index"])
        committed = float(candidate["committed_insts"])
        core_bias = 0 if core_index == 1 else 1
        if not math.isnan(target):
            return (
                abs(committed - target),
                core_bias,
                core_index,
            )
        return (
            core_bias,
            -committed,
            core_index,
        )

    chosen = sorted(filtered, key=sort_key)[0]
    return chosen


def load_metadata(run_dir):
    p = run_dir / "run_metadata.json"
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def infer_run_identity(run_name, metadata):
    predictor = metadata.get("predictor", run_name)
    counter_bits  = math.nan
    window_states = math.nan
    table_size    = math.nan

    if predictor == "CAMP":
        s = metadata.get("predictor_settings", {})
        counter_bits  = s.get("counter_bits",   math.nan)
        window_states = s.get("mlp_window_states", math.nan)
        table_size    = s.get("confidence_table_size_bits",
                              s.get("table_size_bits", math.nan))
    elif predictor == "LocalBP":
        s = metadata.get("predictor_settings", {})
        counter_bits = s.get("counter_bits",   math.nan)
        table_size   = s.get("table_size_bits", math.nan)
    else:
        # Fallback: try to parse from directory name
        cm = RUN_NAME_CAMP.match(run_name)
        lm = RUN_NAME_LOCAL.match(run_name)
        if cm:
            predictor     = "CAMP"
            counter_bits  = int(cm.group("bits"))
            window_states = int(cm.group("window"))
            table_size    = int(cm.group("size"))
        elif lm:
            predictor    = "LocalBP"
            counter_bits = int(lm.group("bits"))
            table_size   = int(lm.group("size"))

    return {
        "predictor":     predictor,
        "counter_bits":  counter_bits,
        "window_states": window_states,
        "table_size_bits": table_size,
    }


def collect_rows(m5out_root):
    rows = []
    for stats_path in sorted(m5out_root.rglob("stats.txt")):
        rel = stats_path.relative_to(m5out_root)
        if len(rel.parts) < 3:
            continue

        benchmark = rel.parts[0]
        run_dir   = stats_path.parent
        run_name  = rel.parts[1]
        stats     = parse_stats(stats_path)
        metadata  = load_metadata(run_dir)
        identity  = infer_run_identity(run_name, metadata)
        measurement_core = select_measurement_core(stats, metadata)
        measurement_prefix = measurement_core.get("prefix", "")
        if not measurement_prefix:
            continue

        cond_predicted = (
            get_prefixed_stat(
                stats,
                measurement_prefix,
                MEASUREMENT_STAT_SUFFIXES["cond_predicted"],
            )
            if measurement_prefix
            else math.nan
        )
        cond_incorrect = (
            get_prefixed_stat(
                stats,
                measurement_prefix,
                MEASUREMENT_STAT_SUFFIXES["cond_incorrect"],
            )
            if measurement_prefix
            else math.nan
        )
        fetched_insts = (
            get_prefixed_stat(
                stats,
                measurement_prefix,
                MEASUREMENT_STAT_SUFFIXES["fetched_insts"],
            )
            if measurement_prefix
            else math.nan
        )
        committed_insts = (
            get_prefixed_stat(
                stats,
                measurement_prefix,
                MEASUREMENT_STAT_SUFFIXES["committed_insts"],
            )
            if measurement_prefix
            else math.nan
        )
        cycles = (
            get_prefixed_stat(
                stats,
                measurement_prefix,
                MEASUREMENT_STAT_SUFFIXES["cycles"],
            )
            if measurement_prefix
            else math.nan
        )
        total_dram      = sum_matching(stats, DRAM_POWER_PATTERN)

        mispred_rate   = cond_incorrect / cond_predicted if cond_predicted > 0 else math.nan
        fetch_commit   = fetched_insts / committed_insts  if committed_insts > 0 else math.nan
        cpi            = cycles / committed_insts          if committed_insts > 0 else math.nan
        branch_mpki    = cond_incorrect * 1000.0 / committed_insts if committed_insts > 0 else math.nan

        rows.append({
            "benchmark":     benchmark,
            "run_name":      run_name,
            "stats_path":    str(stats_path),
            "predictor":     identity["predictor"],
            "measurement_phase": measurement_core.get("phase", ""),
            "measurement_core_index": measurement_core.get("core_index", math.nan),
            "measurement_core_prefix": measurement_prefix,
            "counter_bits":  identity["counter_bits"],
            "window_states": identity["window_states"],
            "table_size_bits": identity["table_size_bits"],
            "cond_predicted":  cond_predicted,
            "cond_incorrect":  cond_incorrect,
            "mispred_rate_pct": mispred_rate * 100.0 if not math.isnan(mispred_rate) else math.nan,
            "fetch_commit_ratio": fetch_commit,
            "cpi":           cpi,
            "branch_mpki":   branch_mpki,
            "dram_power_mw": total_dram if total_dram > 0 else math.nan,
            "sim_seconds":   stats.get("simSeconds", math.nan),
            "host_seconds":  stats.get("hostSeconds", math.nan),
            "total_sim_insts": stats.get("simInsts", math.nan),
            "target_measure_insts": metadata.get("measure_insts", math.nan),
        })
    return rows


# ---------------------------------------------------------------------------
# Summary CSV / MD
# ---------------------------------------------------------------------------

def save_summary(df, plot_dir):
    df.to_csv(plot_dir / "summary.csv", index=False)

    lines = []
    pred_means = (
        df.groupby("predictor")["mispred_rate_pct"]
        .mean()
        .sort_values()
    )
    lines.append("# Branch-Predictor Study — Summary")
    lines.append("")
    lines.append("## Average conditional misprediction rate (%) across all workloads")
    lines.append("")
    for label, val in pred_means.items():
        lines.append(f"- {label}: {val:.3f}%")
    lines.append("")

    camp = df[df["predictor"] == "CAMP"]
    if not camp.empty:
        best = camp.sort_values("mispred_rate_pct").iloc[0]
        lines.append(
            f"Best CAMP config: cb={int(best['counter_bits'])} "
            f"ws={int(best['window_states'])} "
            f"cts={int(best['table_size_bits'])} "
            f"on {best['benchmark']} → {best['mispred_rate_pct']:.3f}%"
        )

    (plot_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Plotting helpers
# ---------------------------------------------------------------------------

_COLORS = [
    "#2166ac", "#4dac26", "#d01c8b", "#f1b6da",
    "#b8e186", "#74add1", "#fdae61", "#f46d43",
]


def get_best_camp_config(df):
    camp_df = df[df["predictor"] == "CAMP"].copy()
    if camp_df.empty:
        return None

    grouped = (
        camp_df.groupby(
            ["counter_bits", "window_states", "table_size_bits"], dropna=False
        )[["mispred_rate_pct", "cpi"]]
        .mean()
        .sort_values(["mispred_rate_pct", "cpi"])
    )
    if grouped.empty:
        return None

    counter_bits, window_states, table_size_bits = grouped.index[0]
    return {
        "counter_bits": int(counter_bits),
        "window_states": int(window_states),
        "table_size_bits": int(table_size_bits),
    }


def format_camp_config(config):
    if not config:
        return "unavailable"
    return (
        f"cb{config['counter_bits']}/"
        f"ws{config['window_states']}/"
        f"cts{config['table_size_bits']}"
    )


def format_predictor_config(predictor, config):
    if predictor == "CAMP":
        return format_camp_config(config)
    if predictor == "LocalBP":
        if not config:
            return "unavailable"
        return f"cb{config['counter_bits']}/cts{config['table_size_bits']}"
    if predictor == "MultiperspectivePerceptron64KB":
        return "64K"
    return "default"


def get_best_predictor_config(df, predictor):
    pred_df = df[df["predictor"] == predictor].copy()
    if pred_df.empty:
        return None

    config_cols = ["counter_bits", "window_states", "table_size_bits"]
    grouped = (
        pred_df.groupby(config_cols, dropna=False)[["mispred_rate_pct", "cpi"]]
        .mean()
        .sort_values(["mispred_rate_pct", "cpi"])
    )
    if grouped.empty:
        return None

    values = grouped.index[0]
    if not isinstance(values, tuple):
        values = (values,)

    config = {}
    for col, value in zip(config_cols, values):
        config[col] = None if pd.isna(value) else int(value)
    return config


def _style_ax(ax, xlabel="", ylabel="", title=""):
    ax.set_xlabel(xlabel, fontsize=10)
    ax.set_ylabel(ylabel, fontsize=10)
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.grid(axis="y", linestyle="--", alpha=0.35, zorder=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


def grouped_bar(
    ax,
    pivot,
    colors=None,
    bar_width=0.8,
):
    """Draw a grouped bar chart on *ax* from a pivot (index=groups, cols=series)."""
    n_groups = len(pivot)
    n_series = len(pivot.columns)
    x = np.arange(n_groups)
    width = bar_width / n_series
    for i, col in enumerate(pivot.columns):
        offset = (i - n_series / 2 + 0.5) * width
        color  = (colors or _COLORS)[i % len(_COLORS)]
        ax.bar(x + offset, pivot[col], width, label=col, color=color, zorder=3)
    ax.set_xticks(x)
    ax.set_xticklabels(pivot.index, rotation=40, ha="right", fontsize=8)


def _format_sweep_value(value):
    if pd.isna(value):
        return ""
    numeric = float(value)
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:g}"


def annotated_heatmap(
    ax,
    pivot,
    title,
    xlabel="Predictor",
    ylabel="Benchmark",
    cmap="YlGnBu",
    value_fmt="{:.2f}",
    column_annotations=None,
    show_values=True,
    cell_annotations=None,
):
    """Draw an annotated heatmap that scales better than dense grouped bars."""
    pivot = pivot.dropna(how="all").dropna(axis=1, how="all")
    if pivot.empty:
        ax.set_visible(False)
        return None

    plot_data = pivot.astype(float)
    mask = np.ma.masked_invalid(plot_data.to_numpy())
    cmap_obj = plt.get_cmap(cmap).copy()
    cmap_obj.set_bad(color="#f3f3f3")

    image = ax.imshow(mask, aspect="auto", cmap=cmap_obj)
    ax.set_xticks(np.arange(len(plot_data.columns)))
    ax.set_xticklabels(plot_data.columns, rotation=30, ha="right", fontsize=8)
    ax.set_yticks(np.arange(len(plot_data.index)))
    ax.set_yticklabels(plot_data.index, fontsize=8)
    ax.set_xlabel(xlabel, fontsize=10)
    ax.set_ylabel(ylabel, fontsize=10)
    ax.set_title(title, fontsize=11, fontweight="bold")
    ax.set_xticks(np.arange(-0.5, len(plot_data.columns), 1), minor=True)
    ax.set_yticks(np.arange(-0.5, len(plot_data.index), 1), minor=True)
    ax.grid(which="minor", color="white", linestyle="-", linewidth=1.2)
    ax.tick_params(which="minor", bottom=False, left=False)
    for spine in ax.spines.values():
        spine.set_visible(False)

    valid = plot_data.to_numpy()[~np.isnan(plot_data.to_numpy())]
    midpoint = float(np.nanmedian(valid)) if valid.size else 0.0
    for row_idx in range(plot_data.shape[0]):
        for col_idx in range(plot_data.shape[1]):
            value = plot_data.iat[row_idx, col_idx]
            if np.isnan(value):
                continue
            text_color = "white" if value >= midpoint else "#1f1f1f"
            annotation = value_fmt.format(value) if show_values else ""
            extra_label = None
            if column_annotations:
                extra_label = column_annotations.get(plot_data.columns[col_idx])
            if cell_annotations:
                extra_label = cell_annotations.get(
                    (plot_data.index[row_idx], plot_data.columns[col_idx]),
                    extra_label,
                )
            if extra_label:
                annotation = extra_label if not annotation else f"{annotation}\n{extra_label}"
            ax.text(
                col_idx,
                row_idx,
                annotation,
                ha="center",
                va="center",
                fontsize=6,
                color=text_color,
            )

    return image


# ---------------------------------------------------------------------------
# Figure 1 — Baseline comparison (per workload, side-by-side bars)
# ---------------------------------------------------------------------------

def _default_camp_label(row):
    return (
        f"CAMP(cb{int(row['counter_bits'])}"
        f"/ws{int(row['window_states'])}"
        f"/cts{int(row['table_size_bits'])})"
    )


def fig1_baseline_comparison(df, plot_dir):
    """Mispred rate + CPI per workload for all baselines and CAMP(default)."""

    best_camp = get_best_camp_config(df)

    # Fixed baselines
    baseline_preds = [
        "LocalBP", "MultiperspectivePerceptron64KB",
        "LTAGE", "MultiperspectivePerceptronTAGE64KB",
        "TournamentBP",
    ]
    base_df = df[df["predictor"].isin(baseline_preds)].copy()
    base_df["label"] = base_df["predictor"].map(BASELINE_LABEL_MAP).fillna(base_df["predictor"])

    # Best CAMP config
    camp_default = df[
        (df["predictor"] == "CAMP") &
        (df["counter_bits"]  == best_camp["counter_bits"]) &
        (df["window_states"] == best_camp["window_states"]) &
        (df["table_size_bits"] == best_camp["table_size_bits"])
    ].copy()
    camp_default["label"] = "CAMP(best)"

    plot_df = pd.concat([base_df, camp_default], ignore_index=True)
    if plot_df.empty:
        return

    benchmarks = sorted(plot_df["benchmark"].unique())

    fig, axes = plt.subplots(2, 1, figsize=(max(11, len(plot_df["label"].unique()) * 1.2), 7.5))

    images = []
    for ax, metric, ylabel in zip(
        axes,
        ["mispred_rate_pct", "cpi"],
        ["Mispred rate (%)", "CPI"],
    ):
        pivot = plot_df.pivot_table(
            index="benchmark", columns="label",
            values=metric, aggfunc="mean",
        ).reindex(benchmarks)
        if pivot.empty or pivot.isna().all(axis=None):
            continue
        image = annotated_heatmap(
            ax,
            pivot,
            title=f"Baseline Predictor Comparison — {ylabel}",
            ylabel="Benchmark",
            value_fmt="{:.2f}",
        )
        if image is not None:
            images.append((ax, image, ylabel))

    for ax, image, ylabel in images:
        fig.colorbar(image, ax=ax, fraction=0.025, pad=0.02, label=ylabel)

    fig.suptitle(
        f"Best CAMP config shown: {format_camp_config(best_camp)}",
        fontsize=10,
        color="dimgray",
    )
    fig.tight_layout(rect=[0, 0, 1, 0.96], h_pad=2.2)
    fig.savefig(plot_dir / "fig1_baseline_comparison.png", dpi=180)
    plt.close(fig)


def fig0_metrics_dashboard(df, plot_dir):
    """Single concise figure with the four core report metrics."""

    predictor_order = ["LocalBP", "MultiperspectivePerceptron64KB", "CAMP"]
    plot_df = (
        df[df["predictor"].isin(predictor_order)]
        .sort_values(["benchmark", "predictor", "mispred_rate_pct", "cpi"])
        .groupby(["benchmark", "predictor"], as_index=False)
        .first()
    )
    if plot_df.empty:
        return
    plot_df["label"] = plot_df["predictor"].map(
        {
            "LocalBP": "LocalBP",
            "MultiperspectivePerceptron64KB": "MLP",
            "CAMP": "CAMP",
        }
    )

    metric_specs = [
        ("mispred_rate_pct", "Mispred rate (%)"),
        ("fetch_commit_ratio", "Fetch / Commit ratio"),
        ("cpi", "CPI"),
        ("dram_power_mw", "DRAM power (mW)"),
    ]
    if plot_df["dram_power_mw"].isna().all():
        metric_specs[-1] = ("sim_seconds", "Simulated seconds")

    benchmarks = sorted(plot_df["benchmark"].unique())
    series_order = ["LocalBP", "MLP", "CAMP"]
    cell_annotations = {}
    for _, row in plot_df.iterrows():
        config = {
            "counter_bits": row.get("counter_bits"),
            "window_states": row.get("window_states"),
            "table_size_bits": row.get("table_size_bits"),
        }
        for key, value in list(config.items()):
            config[key] = None if pd.isna(value) else int(value)
        cell_annotations[(row["benchmark"], row["label"])] = format_predictor_config(
            row["predictor"], config
        )
    fig, axes = plt.subplots(2, 2, figsize=(13, max(8, len(benchmarks) * 1.9)))

    images = []
    for ax, (metric, ylabel) in zip(axes.flatten(), metric_specs):
        pivot = plot_df.pivot_table(
            index="benchmark",
            columns="label",
            values=metric,
            aggfunc="mean",
        ).reindex(index=benchmarks, columns=series_order)

        if pivot.empty or pivot.isna().all(axis=None):
            ax.set_visible(False)
            continue

        image = annotated_heatmap(
            ax,
            pivot,
            title=ylabel,
            ylabel="Benchmark",
            value_fmt="{:.2f}",
            show_values=True,
            cell_annotations=cell_annotations,
        )
        if image is not None:
            images.append((ax, image, ylabel))

    for ax, image, ylabel in images:
        fig.colorbar(image, ax=ax, fraction=0.03, pad=0.02, label=ylabel)

    fig.suptitle(
        "Branch-Predictor Metrics Dashboard",
        fontsize=13,
        fontweight="bold",
    )
    fig.text(
        0.5,
        0.93,
        "Tiles show the best available config for each workload/predictor pair.",
        ha="center",
        fontsize=9,
        color="dimgray",
    )
    fig.tight_layout(rect=[0, 0, 1, 0.96], h_pad=2.5, w_pad=2)
    fig.savefig(plot_dir / "fig0_metrics_dashboard.png", dpi=180)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Sweep figures (2, 3, 4) — averaged across workloads
# ---------------------------------------------------------------------------

def _camp_sweep_fig(
    camp_df,
    sweep_col,
    fixed,
    xlabel,
    title_prefix,
    output_path,
):
    """Trend chart: average sweep response with point labels for each setting."""

    mask = pd.Series(True, index=camp_df.index)
    for col, val in fixed.items():
        mask &= camp_df[col] == val
    data = camp_df[mask].copy()
    if data.empty:
        return

    # Sort the sweep axis numerically
    data[sweep_col] = pd.to_numeric(data[sweep_col], errors="coerce")
    data = data.dropna(subset=[sweep_col])
    sweep_vals = sorted(data[sweep_col].unique())
    if not sweep_vals:
        return

    summary = (
        data.groupby(sweep_col)[["mispred_rate_pct", "cpi"]]
        .mean()
        .reindex(sweep_vals)
    )

    fig, axes = plt.subplots(1, 2, figsize=(10.5, 4.2))
    x_vals = summary.index.to_numpy(dtype=float)
    x_labels = [_format_sweep_value(v) for v in summary.index]

    for ax, col, ylabel, color in zip(
        axes,
        ["mispred_rate_pct", "cpi"],
        ["Mispred rate (%)", "CPI"],
        [_COLORS[0], _COLORS[1]],
    ):
        vals = summary[col].to_numpy(dtype=float)
        ax.plot(x_vals, vals, color=color, marker="o", linewidth=2.2, markersize=6, zorder=3)
        ax.fill_between(x_vals, vals, color=color, alpha=0.12, zorder=2)
        for x, y in zip(x_vals, vals):
            ax.annotate(
                f"{y:.2f}",
                xy=(x, y),
                xytext=(0, 7),
                textcoords="offset points",
                ha="center",
                fontsize=8,
            )
        ax.set_xticks(x_vals)
        ax.set_xticklabels(x_labels)
        _style_ax(
            ax,
            xlabel=xlabel,
            ylabel=ylabel,
            title=f"{title_prefix} — {ylabel}",
        )

    # Annotate fixed params
    fixed_str = "  |  ".join(f"{k}={v}" for k, v in fixed.items())
    fig.suptitle(fixed_str, fontsize=9, color="grey")
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(output_path, dpi=180)
    plt.close(fig)


def fig2_table_size_sweep(camp_df, plot_dir):
    _camp_sweep_fig(
        camp_df,
        sweep_col="table_size_bits",
        fixed={"counter_bits": DEFAULT_COUNTER_BITS, "window_states": DEFAULT_WINDOW_STATES},
        xlabel="Confidence table size (bits)",
        title_prefix="CAMP: Vary Hash Table Size",
        output_path=plot_dir / "fig2_table_size_sweep.png",
    )


def fig3_counter_window_heatmap(camp_df, plot_dir):
    data = camp_df[camp_df["table_size_bits"] == DEFAULT_TABLE_SIZE].copy()
    if data.empty:
        return

    data["counter_bits"] = pd.to_numeric(data["counter_bits"], errors="coerce")
    data["window_states"] = pd.to_numeric(data["window_states"], errors="coerce")
    data = data.dropna(subset=["counter_bits", "window_states", "mispred_rate_pct"])
    if data.empty:
        return

    counter_vals = sorted(data["counter_bits"].unique())
    window_vals = sorted(data["window_states"].unique())
    pivot = data.pivot_table(
        index="window_states",
        columns="counter_bits",
        values="mispred_rate_pct",
        aggfunc="mean",
    ).reindex(index=window_vals, columns=counter_vals)

    fig, ax = plt.subplots(figsize=(7, 4.8))
    image = annotated_heatmap(
        ax,
        pivot,
        title="CAMP: Counter Bits vs. Window States — Mispred rate (%)",
        xlabel="Saturating counter bits",
        ylabel="MLP window states",
        value_fmt="{:.2f}",
        show_values=True,
    )
    if image is not None:
        fig.colorbar(image, ax=ax, fraction=0.035, pad=0.03, label="Mispred rate (%)")

    fig.suptitle(
        f"Fixed table_size_bits={DEFAULT_TABLE_SIZE}",
        fontsize=9,
        color="dimgray",
    )
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(plot_dir / "fig3_counter_window_heatmap.png", dpi=180)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    args = parse_args()
    m5out_root = Path(args.m5out_root).resolve()
    plot_dir   = Path(args.plot_dir).resolve()
    plot_dir.mkdir(parents=True, exist_ok=True)

    rows = collect_rows(m5out_root)
    if not rows:
        raise SystemExit(f"No stats.txt files found under {m5out_root}")
    df = pd.DataFrame(rows)

    save_summary(df, plot_dir)

    camp_df = df[df["predictor"] == "CAMP"].copy()

    output_paths = [
        plot_dir / "fig0_metrics_dashboard.png",
        plot_dir / "fig1_baseline_comparison.png",
        plot_dir / "fig2_table_size_sweep.png",
        plot_dir / "fig3_counter_window_heatmap.png",
        plot_dir / "fig3_counter_bits_sweep.png",
        plot_dir / "fig4_window_states_sweep.png",
    ]
    for output_path in output_paths:
        if output_path.exists():
            output_path.unlink()

    fig0_metrics_dashboard(df, plot_dir)
    fig1_baseline_comparison(df, plot_dir)
    fig2_table_size_sweep(camp_df, plot_dir)
    fig3_counter_window_heatmap(camp_df, plot_dir)

    print(f"Plots written to {plot_dir}/")
    for output_path in output_paths:
        if output_path.exists():
            print("  {}".format(output_path.name))


if __name__ == "__main__":
    main()
