"""
Run SPEC CPU2017 workloads on gem5 O3 cores with configurable branch
predictors, including the custom CAMP predictor.

The simulation boots on KVM, warms on a configurable CPU model, and then
switches to O3 for the detailed measurement window.

gem5 v25 compatibility notes
-----------------------------
In gem5 v25, the kernel-boot sequence fires *hypercalls* (IDs 1, 2, 3) that
are dispatched by their own ExitHandler subclasses.  These are completely
separate from the classic ExitEvent.EXIT (hypercall 0).

The SPEC CPU2017 disk image's ``runscript.sh`` calls ``m5 exit`` three times:
  1. Before ``runcpu`` starts  → classic ExitEvent.EXIT → generator step 1
  2. After  ``runcpu`` finishes → classic ExitEvent.EXIT → generator step 2
  3. After file copies finish  → classic ExitEvent.EXIT → generator step 3

We use two exit paths together:
  • ExitEvent.EXIT handles guest `m5 exit` instructions from the SPEC runscript
  • Per-core `scheduleInstStop(..., "a thread reached the max instruction
    count")` produces ExitEvent.MAX_INSTS for warmup-complete and
    measurement-complete

We also register custom hypercall handlers (inside main() so errors are
captured by the top-level try/except):
  • KernelBootedExitHandler (hypercall 1): just log, return False
  • AfterBootExitHandler    (hypercall 2): just log, return False
  • AfterBootScriptExitHandler (hypercall 3): log, return **False**
    This is critical – after_boot.sh finishes AFTER our measurement ends on
    long ref runs but BEFORE it ends on short test/train runs.  Returning
    False prevents the simulation from being killed before stats are dumped.
"""

import argparse
import json
import os
import sys
import time
import traceback

import m5

from gem5.coherence_protocol import CoherenceProtocol
from gem5.components.boards.mem_mode import MemMode
from gem5.components.boards.x86_board import X86Board
from gem5.components.cachehierarchies.ruby.mesi_two_level_cache_hierarchy import (
    MESITwoLevelCacheHierarchy,
)
from gem5.components.memory import DualChannelDDR4_2400
from gem5.components.processors.cpu_types import CPUTypes, get_mem_mode
from gem5.components.processors.simple_core import SimpleCore
from gem5.components.processors.simple_switchable_processor import (
    SimpleSwitchableProcessor,
)
from gem5.components.processors.switchable_processor import SwitchableProcessor
from gem5.isas import ISA
from gem5.resources.resource import DiskImageResource, Resource
from gem5.simulate.exit_event import ExitEvent
from gem5.simulate.exit_handler import (
    AfterBootExitHandler,
    AfterBootScriptExitHandler,
    KernelBootedExitHandler,
)
from gem5.simulate.simulator import Simulator
from gem5.utils.requires import requires

from m5.objects import (
    BranchPredictor,
    CAMP,
    LTAGE,
    LocalBP,
    MultiperspectivePerceptron64KB,
    MultiperspectivePerceptronTAGE64KB,
    TournamentBP,
)
from m5.util import fatal, warn

MAX_INSTS_CAUSE = "a thread reached the max instruction count"

BENCHMARK_CHOICES = [
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

SIZE_CHOICES = ["test", "train", "ref"]
PREDICTOR_CHOICES = [
    "LocalBP",
    "TournamentBP",
    "LTAGE",
    "MultiperspectivePerceptron64KB",
    "MultiperspectivePerceptronTAGE64KB",
    "CAMP",
]
WARMUP_MODE_CHOICES = ["kvm", "timing", "o3"]


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Run SPEC CPU2017 benchmarks with LocalBP, MPP, or CAMP on an "
            "O3 CPU after the KVM boot phase."
        )
    )
    parser.add_argument(
        "--image",
        type=str,
        required=True,
        help="Full path to the SPEC CPU2017 disk image.",
    )
    parser.add_argument(
        "--partition",
        type=str,
        default=None,
        help="Root partition of the SPEC disk image.",
    )
    parser.add_argument(
        "--benchmark",
        type=str,
        required=True,
        choices=BENCHMARK_CHOICES,
        help="Benchmark program to execute.",
    )
    parser.add_argument(
        "--size",
        type=str,
        required=True,
        choices=SIZE_CHOICES,
        help="SPEC input size to execute.",
    )
    parser.add_argument(
        "--predictor",
        type=str,
        required=True,
        choices=PREDICTOR_CHOICES,
        help="Conditional branch predictor to use during O3 measurement.",
    )
    parser.add_argument(
        "--warmup-insts",
        type=int,
        default=1_000_000,
        help="Instructions to warm before the measured O3 window.",
    )
    parser.add_argument(
        "--warmup-mode",
        type=str,
        default="timing",
        choices=WARMUP_MODE_CHOICES,
        help=(
            "Warmup core type after boot. 'timing' is the safe default on SCC; "
            "'kvm' requires host perf support for instruction-stop events."
        ),
    )
    parser.add_argument(
        "--measure-insts",
        type=int,
        default=100_000_000,
        help="Instructions to measure on O3 after warmup.",
    )
    parser.add_argument(
        "--confidence-table-size",
        type=int,
        default=8192,
        help="Number of entries in the CAMP/LocalBP counter table.",
    )
    parser.add_argument(
        "--counter-bits",
        type=int,
        default=2,
        help="Bits per LocalBP or CAMP saturating counter.",
    )
    parser.add_argument(
        "--mlp-window-states",
        type=int,
        default=2,
        help="Number of centered confidence states that delegate to the MLP.",
    )
    parser.add_argument(
        "--run-tag",
        type=str,
        default="",
        help="Optional user-visible label recorded in run metadata.",
    )
    return parser.parse_args()


def normalize_image_path(image_path):
    if image_path.startswith("/"):
        return image_path
    return os.path.abspath(image_path)


def validate_args(args):
    if args.warmup_insts <= 0:
        fatal("--warmup-insts must be positive.\n")

    if args.measure_insts <= 0:
        fatal("--measure-insts must be positive.\n")

    if args.confidence_table_size <= 0:
        fatal("--confidence-table-size must be positive.\n")

    if args.confidence_table_size & (args.confidence_table_size - 1):
        fatal("--confidence-table-size must be a power of two.\n")

    if args.counter_bits <= 0 or args.counter_bits > 8:
        fatal("--counter-bits must be in the range [1, 8].\n")

    if args.mlp_window_states <= 0:
        fatal("--mlp-window-states must be positive.\n")


def build_predictor(args):
    if args.predictor == "LocalBP":
        cond_bp = LocalBP(
            localPredictorSize=args.confidence_table_size,
            localCtrBits=args.counter_bits,
        )
        settings = {
            "predictor": args.predictor,
            "table_size_entries": args.confidence_table_size,
            "table_size_bits": args.confidence_table_size,
            "counter_bits": args.counter_bits,
        }
    elif args.predictor == "TournamentBP":
        cond_bp = TournamentBP()
        settings = {"predictor": args.predictor}
    elif args.predictor == "LTAGE":
        cond_bp = LTAGE()
        settings = {"predictor": args.predictor}
    elif args.predictor == "MultiperspectivePerceptron64KB":
        cond_bp = MultiperspectivePerceptron64KB()
        settings = {"predictor": args.predictor}
    elif args.predictor == "MultiperspectivePerceptronTAGE64KB":
        cond_bp = MultiperspectivePerceptronTAGE64KB()
        settings = {"predictor": args.predictor}
    elif args.predictor == "CAMP":
        cond_bp = CAMP(
            confidenceTableSize=args.confidence_table_size,
            counterBits=args.counter_bits,
            mlpWindowStates=args.mlp_window_states,
            simple_bp=LocalBP(
                localPredictorSize=args.confidence_table_size,
                localCtrBits=args.counter_bits,
            ),
        )
        settings = {
            "predictor": args.predictor,
            "confidence_table_entries": args.confidence_table_size,
            "confidence_table_size_bits": args.confidence_table_size,
            "counter_bits": args.counter_bits,
            "mlp_window_states": args.mlp_window_states,
        }
    else:
        fatal(f"Unsupported predictor: {args.predictor}")

    return cond_bp, settings


def predictor_settings_from_args(args):
    if args.predictor == "LocalBP":
        return {
            "predictor": args.predictor,
            "table_size_entries": args.confidence_table_size,
            "table_size_bits": args.confidence_table_size,
            "counter_bits": args.counter_bits,
        }
    if args.predictor == "TournamentBP":
        return {"predictor": args.predictor}
    if args.predictor == "LTAGE":
        return {"predictor": args.predictor}
    if args.predictor == "MultiperspectivePerceptron64KB":
        return {"predictor": args.predictor}
    if args.predictor == "MultiperspectivePerceptronTAGE64KB":
        return {"predictor": args.predictor}
    if args.predictor == "CAMP":
        return {
            "predictor": args.predictor,
            "confidence_table_entries": args.confidence_table_size,
            "confidence_table_size_bits": args.confidence_table_size,
            "counter_bits": args.counter_bits,
            "mlp_window_states": args.mlp_window_states,
        }
    fatal(f"Unsupported predictor: {args.predictor}")


def log(message):
    print(message, flush=True)


def write_status_file(state, extra=None):
    if not getattr(m5.options, "outdir", None):
        return

    os.makedirs(m5.options.outdir, exist_ok=True)
    payload = {
        "state": state,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    if extra:
        payload.update(extra)

    status_path = os.path.join(m5.options.outdir, "run_status.json")
    with open(status_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)


def write_run_metadata(args, predictor_settings):
    os.makedirs(m5.options.outdir, exist_ok=True)
    metadata = {
        "benchmark": args.benchmark,
        "size": args.size,
        "predictor": args.predictor,
        "warmup_insts": args.warmup_insts,
        "warmup_mode": args.warmup_mode,
        "measure_insts": args.measure_insts,
        "run_tag": args.run_tag,
        "outdir": m5.options.outdir,
        "disk_image": args.image,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "predictor_settings": predictor_settings,
    }
    metadata_path = os.path.join(m5.options.outdir, "run_metadata.json")
    with open(metadata_path, "w", encoding="utf-8") as handle:
        json.dump(metadata, handle, indent=2, sort_keys=True)


def kvm_perf_available():
    if os.geteuid() == 0:
        return True

    try:
        with open("/proc/sys/kernel/perf_event_paranoid", "r", encoding="ascii") as handle:
            paranoid = int(handle.read().strip())
    except (OSError, ValueError):
        return False

    return paranoid <= 1


class ThreePhaseSwitchableProcessor(SwitchableProcessor):
    """Switch KVM boot cores to warmup cores and then to detailed O3 cores."""

    def __init__(
        self,
        starting_core_type,
        warmup_core_type,
        measure_core_type,
        num_cores,
        isa,
    ):
        self._mem_mode = get_mem_mode(starting_core_type)

        switchable_cores = {
            "boot": [
                SimpleCore(cpu_type=starting_core_type, core_id=i, isa=isa)
                for i in range(num_cores)
            ],
            "warmup": [
                SimpleCore(cpu_type=warmup_core_type, core_id=i, isa=isa)
                for i in range(num_cores)
            ],
            "measure": [
                SimpleCore(cpu_type=measure_core_type, core_id=i, isa=isa)
                for i in range(num_cores)
            ],
        }

        super().__init__(switchable_cores=switchable_cores, starting_cores="boot")

    def incorporate_processor(self, board):
        super().incorporate_processor(board=board)

        if (
            board.get_cache_hierarchy().is_ruby()
            and self._mem_mode == MemMode.ATOMIC
        ):
            warn(
                "Using an atomic core with Ruby will result in "
                "'atomic_noncaching' memory mode. This will skip caching "
                "completely."
            )
            self._mem_mode = MemMode.ATOMIC_NONCACHING

        board.set_mem_mode(self._mem_mode)


def main():
    args = parse_args()
    args.image = normalize_image_path(args.image)
    validate_args(args)

    if args.warmup_mode == "kvm" and not kvm_perf_available():
        warn(
            "KVM warmup requested, but host perf_event access is unavailable. "
            "Falling back to TimingSimpleCPU warmup instead."
        )
        args.warmup_mode = "timing"

    write_status_file(
        "starting",
        {
            "argv": sys.argv,
            "benchmark": args.benchmark,
            "predictor": args.predictor,
            "run_tag": args.run_tag,
        },
    )

    requires(
        isa_required=ISA.X86,
        coherence_protocol_required=CoherenceProtocol.MESI_TWO_LEVEL,
        kvm_required=True,
    )

    if not os.path.exists(args.image):
        warn("Disk image not found!")
        fatal(f"The disk image is not found at {args.image}")

    cache_hierarchy = MESITwoLevelCacheHierarchy(
        l1d_size="16kB",
        l1d_assoc=8,
        l1i_size="16kB",
        l1i_assoc=8,
        l2_size="1MB",
        l2_assoc=16,
        num_l2_banks=2,
    )
    memory = DualChannelDDR4_2400(size="3GB")

    if args.warmup_mode == "timing":
        processor = ThreePhaseSwitchableProcessor(
            starting_core_type=CPUTypes.KVM,
            warmup_core_type=CPUTypes.TIMING,
            measure_core_type=CPUTypes.O3,
            isa=ISA.X86,
            num_cores=2,
        )
        measure_cores = processor.measure
        for proc in processor.boot:
            proc.core.usePerf = False
    else:
        processor = SimpleSwitchableProcessor(
            starting_core_type=CPUTypes.KVM,
            switch_core_type=CPUTypes.O3,
            isa=ISA.X86,
            num_cores=2,
        )
        measure_cores = processor._switchable_cores["switch"]

        for proc in processor.start:
            # KVM instruction-stop events rely on perf counters. Keep them
            # enabled only for explicit KVM warmup.
            proc.core.usePerf = args.warmup_mode == "kvm"

    predictor_settings = predictor_settings_from_args(args)
    write_run_metadata(args, predictor_settings)

    for proc in measure_cores:
        cond_bp, _ = build_predictor(args)
        proc.core.branchPred = BranchPredictor(conditionalBranchPred=cond_bp)

    board = X86Board(
        clk_freq="3GHz",
        processor=processor,
        memory=memory,
        cache_hierarchy=cache_hierarchy,
    )

    guest_output_dir = "_".join(
        part
        for part in [
            "camp",
            args.benchmark.replace(".", "_"),
            args.predictor,
            args.run_tag or time.strftime("%Y%m%d_%H%M%S"),
        ]
        if part
    )

    # Create the host-side directory that m5 writefile will write SPEC results
    # into. Without this, gem5 panics when runscript.sh calls `m5 writefile`.
    host_output_dir = os.path.join(m5.options.outdir, guest_output_dir)
    host_output_dir_exists = os.path.isdir(host_output_dir)
    try:
        os.makedirs(host_output_dir, exist_ok=True)
    except OSError as exc:
        fatal(f"Failed to create host output directory {host_output_dir}: {exc}\n")
    if host_output_dir_exists:
        warn(f"Output directory already exists: {host_output_dir}")

    board.set_kernel_disk_workload(
        kernel=Resource("x86-linux-kernel-4.19.83"),
        disk_image=DiskImageResource(
            args.image,
            root_partition=args.partition,
        ),
        readfile_contents=f"{args.benchmark} {args.size} {guest_output_dir}",
    )

    # -----------------------------------------------------------------------
    # gem5 v25 hypercall-based boot event handlers.
    #
    # These are defined INSIDE main() so that any errors are captured by the
    # top-level try/except and written to run_error.txt.
    #
    # The custom handlers override the hypercall handlers in ExitHandler's
    # class-level registry (_handler_map).  The key change vs. stock gem5:
    #   AfterBootScriptExitHandler (hypercall 3) now returns False instead of
    #   True, preventing the simulation from being killed when after_boot.sh
    #   finishes. This is important for short SPEC sizes (test/train) where the
    #   benchmark may complete before our measurement window is done.
    # -----------------------------------------------------------------------

    class CAMPKernelBootedExitHandler(KernelBootedExitHandler):
        """Hypercall 1 – kernel has booted. Log and continue."""
        def _process(self, simulator):
            log("Kernel booted. Waiting for runscript.sh to start.")
            write_status_file("kernel_booted")

        def _exit_simulation(self):
            return False  # KernelBootedExitHandler already returns False but be explicit

    class CAMPAfterBootExitHandler(AfterBootExitHandler):
        """Hypercall 2 – after_boot.sh (runscript.sh) started."""
        def _process(self, simulator):
            log("after_boot.sh / runscript.sh started inside the guest.")
            write_status_file("after_boot_started")

        def _exit_simulation(self):
            return False

    class CAMPAfterBootScriptExitHandler(AfterBootScriptExitHandler):
        """Hypercall 3 – after_boot.sh finished.

        CRITICAL: return False here so the simulation is not terminated when
        after_boot.sh exits.  On short SPEC runs (test/train) the benchmark
        may finish before our measurement window closes.  If we returned True
        (the base-class default) stats would never be dumped.
        """
        def _process(self, simulator):
            log(
                "after_boot.sh finished inside the guest. "
                "Measurement may still be in progress."
            )
            write_status_file(
                "after_boot_finished",
                {"last_exit_cause": simulator.get_last_exit_event_cause()},
            )

        def _exit_simulation(self):
            return False  # <<< THE KEY FIX vs. the base class

    run_state = {
        "phase": "boot",
        "guest_exit_count": 0,
    }
    benchmark_core_index = 1

    def schedule_phase(core, inst_count):
        core.scheduleInstStop(
            0,
            inst_count,
            MAX_INSTS_CAUSE,
        )

    def handle_exit():
        while True:
            run_state["guest_exit_count"] += 1

            if run_state["phase"] == "boot":
                if args.warmup_mode == "o3":
                    log(
                        "Done booting Linux. Switching to O3 and scheduling "
                        f"{args.warmup_insts:,} warmup instructions."
                    )
                    write_status_file("switching_to_o3")
                    processor.switch()
                    write_status_file("o3_warmup")
                elif args.warmup_mode == "timing":
                    log(
                        "Done booting Linux. Switching to TimingSimpleCPU and "
                        f"scheduling {args.warmup_insts:,} warmup instructions."
                    )
                    write_status_file("switching_to_timing")
                    processor.switch_to_processor("warmup")
                    write_status_file("timing_warmup")
                else:
                    log(
                        "Done booting Linux. Scheduling "
                        f"{args.warmup_insts:,} warmup instructions on KVM "
                        "before switching to O3."
                    )
                    write_status_file("kvm_warmup")

                schedule_phase(
                    processor.get_cores()[benchmark_core_index].core,
                    args.warmup_insts,
                )
                run_state["phase"] = "warmup"
                yield False
                continue

            if run_state["phase"] in {"warmup", "measurement"}:
                log(
                    "Guest m5 exit observed during "
                    f"{run_state['phase']}; continuing until the scheduled "
                    "instruction stop is reached."
                )
                write_status_file(
                    "guest_exit_observed",
                    {
                        "phase": run_state["phase"],
                        "guest_exit_count": run_state["guest_exit_count"],
                    },
                )
                yield False
                continue

            log("Guest exit observed after completion. Stopping simulation.")
            yield True

    def handle_max_insts():
        while True:
            if run_state["phase"] == "warmup":
                if args.warmup_mode == "kvm":
                    log(
                        "KVM warmup complete. Switching to O3 for the detailed "
                        "measurement window."
                    )
                    write_status_file("switching_to_o3")
                    processor.switch()
                elif args.warmup_mode == "timing":
                    log(
                        "Timing warmup complete. Switching to O3 for the "
                        "detailed measurement window."
                    )
                    write_status_file("switching_to_o3")
                    processor.switch_to_processor("measure")

                log("Warmup complete. Resetting stats and starting measurement.")
                m5.stats.reset()
                log(
                    f"Starting O3 measurement for {args.measure_insts:,} "
                    "instructions."
                )
                write_status_file("o3_measurement")
                schedule_phase(
                    processor.get_cores()[benchmark_core_index].core,
                    args.measure_insts,
                )
                run_state["phase"] = "measurement"
                yield False
                continue

            if run_state["phase"] == "measurement":
                log("Measurement complete. Dumping stats.")
                m5.stats.dump()
                write_status_file("completed")
                run_state["phase"] = "completed"
                yield True
                continue

            log(
                "Unexpected MAX_INSTS exit while in phase "
                f"{run_state['phase']}. Dumping stats and stopping."
            )
            m5.stats.dump()
            write_status_file(
                "unexpected_max_insts",
                {"phase": run_state["phase"]},
            )
            yield True

    def handle_schedule():
        log("Scheduled tick exit reached. Dumping stats.")
        m5.stats.dump()
        write_status_file("scheduled_exit")
        yield True

    simulator = Simulator(
        board=board,
        on_exit_event={
            ExitEvent.EXIT: handle_exit(),
            ExitEvent.MAX_INSTS: handle_max_insts(),
            ExitEvent.SCHEDULED_TICK: handle_schedule(),
        },
    )

    global_start = time.time()
    log(f"CPUs: {processor.get_cores()}")
    log("Running the simulation")
    if args.warmup_mode == "kvm":
        log("Using KVM for boot and warmup, then O3 for detailed measurement")
    elif args.warmup_mode == "timing":
        log("Using KVM for boot, TimingSimpleCPU for warmup, then O3 for detailed measurement")
    else:
        log("Using KVM for boot, then O3 for warmup and detailed measurement")
    m5.stats.initSimStats()
    m5.stats.reset()

    simulator.show_exit_event_messages()
    simulator.run()

    log("\nDone with the simulation")
    log(f"Ran a total of {simulator.get_current_tick() / 1e12} simulated seconds")
    log(
        "Total wallclock time: %.2fs, %.2f min"
        % (time.time() - global_start, (time.time() - global_start) / 60)
    )


if __name__ in ("__main__", "__m5_main__"):
    try:
        main()
    except Exception:
        error = traceback.format_exc()
        print(error, file=sys.stderr, flush=True)
        try:
            write_status_file("failed", {"traceback": error})
            error_path = os.path.join(m5.options.outdir, "run_error.txt")
            with open(error_path, "w", encoding="utf-8") as handle:
                handle.write(error)
        except Exception:
            pass
        raise
