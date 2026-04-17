#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
BUNDLE_ROOT="$SCRIPT_DIR"
MODE="copy"
TARGET_ROOT=""

print_usage() {
    cat <<'EOF'
Usage: ./test_files/setup.sh [options]

Install the bundled project files into an existing spec-2017 tree.

Assumptions:
  - This cloned bundle lives somewhere under an existing parent directory named
    `spec-2017`, or you provide that path explicitly with --target.
  - The target tree already has the general project layout (for example
    `gem5/src/cpu/pred`, `gem5/ec513_custom`, and `gem5/bu_scc_jobs`).

Options:
  --target PATH   Install into PATH instead of auto-detecting the nearest
                  ancestor named `spec-2017`
  --move          Move files from this bundle into the target tree
  --copy          Copy files into the target tree and keep this bundle intact
                  (default)
  --help          Show this help message
EOF
}

find_spec_root() {
    local dir="$SCRIPT_DIR"

    while [[ "$dir" != "/" ]]; do
        dir=$(dirname "$dir")
        if [[ "$(basename "$dir")" == "spec-2017" && -d "$dir/gem5" ]]; then
            printf '%s\n' "$dir"
            return 0
        fi
    done

    return 1
}

install_file() {
    local rel_path="$1"
    local src="$BUNDLE_ROOT/$rel_path"
    local dst="$TARGET_ROOT/$rel_path"

    mkdir -p "$(dirname "$dst")"

    if [[ "$MODE" == "move" ]]; then
        mv "$src" "$dst"
        printf 'Moved  %s -> %s\n' "$rel_path" "$dst"
    else
        cp -f "$src" "$dst"
        printf 'Copied %s -> %s\n' "$rel_path" "$dst"
    fi
}

install_tree_contents() {
    local rel_dir="$1"
    local src_dir="$BUNDLE_ROOT/$rel_dir"
    local dst_dir="$TARGET_ROOT/$rel_dir"

    mkdir -p "$dst_dir"

    while IFS= read -r -d '' src_path; do
        local rel_path="${src_path#$BUNDLE_ROOT/}"
        install_file "$rel_path"
    done < <(find "$src_dir" -type f -print0 | sort -z)
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)
            TARGET_ROOT="$2"
            shift 2
            ;;
        --move)
            MODE="move"
            shift
            ;;
        --copy)
            MODE="copy"
            shift
            ;;
        --help)
            print_usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            print_usage >&2
            exit 1
            ;;
    esac
done

if [[ -z "$TARGET_ROOT" ]]; then
    if ! TARGET_ROOT=$(find_spec_root); then
        cat >&2 <<'EOF'
Could not auto-detect the target spec-2017 directory.
Clone this bundle somewhere under an existing `spec-2017` parent directory,
or re-run with:

  ./test_files/setup.sh --target /path/to/spec-2017
EOF
        exit 1
    fi
fi

TARGET_ROOT=$(cd "$TARGET_ROOT" && pwd)

if [[ ! -d "$TARGET_ROOT/gem5" ]]; then
    echo "Target does not look like a spec-2017 tree: $TARGET_ROOT" >&2
    exit 1
fi

if [[ "$TARGET_ROOT" == "$(cd "$BUNDLE_ROOT/.." && pwd)" ]]; then
    echo "Refusing to install into the bundle checkout itself." >&2
    echo "Point --target at the surrounding spec-2017 tree instead." >&2
    exit 1
fi

echo "Installing bundle into: $TARGET_ROOT"
echo "Mode: $MODE"

install_file "gem5/src/cpu/pred/camp.cc"
install_file "gem5/src/cpu/pred/camp.hh"
install_file "gem5/src/cpu/pred/CAMP_predictor.py"
install_file "gem5/ec513_custom/simulate_CAMP.py"
install_file "gem5/run_project_benchmark.sh"
install_tree_contents "gem5/bu_scc_jobs"
install_file "project_answers.py"
install_tree_contents "project_plot"

cat <<EOF

Install complete.

Next steps:
  1. cd "$TARGET_ROOT"
  2. ./setup.sh
  3. source sourceme
  4. cd gem5 && scons build/X86/gem5.opt -j \${BUILD_JOBS:-\$(command -v nproc >/dev/null 2>&1 && nproc || echo 4)}
EOF
