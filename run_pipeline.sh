#!/usr/bin/env bash
# =============================================================================
# run_pipeline.sh  —  COMP-5700 Secure Software Process Project Runner
#
# Usage:
#   ./run_pipeline.sh <pdf_dir>
#
# Example:
#   ./run_pipeline.sh /path/to/pdfs
#   ./run_pipeline.sh .               # if PDFs are in the same directory
#
# The directory must contain: cis-r1.pdf, cis-r2.pdf, cis-r3.pdf, cis-r4.pdf
#
# What this script does:
#   Phase 1 — Task 1: Extract KDEs from each unique PDF (4 runs total)
#               cis-r1.pdf → cis-r1-kdes.yaml
#               cis-r2.pdf → cis-r2-kdes.yaml
#               cis-r3.pdf → cis-r3-kdes.yaml
#               cis-r4.pdf → cis-r4-kdes.yaml
#
#   Phase 2 — Tasks 2 & 3: Run all 9 input combinations using cached YAMLs
#               r1+r1, r1+r2, r1+r3, r1+r4
#               r2+r2, r2+r3, r2+r4
#               r3+r3, r3+r4
#
# Requirements:
#   - Python 3.9+
#   - kubescape installed and on your PATH
#       Install: curl -s https://raw.githubusercontent.com/kubescape/kubescape/master/install.sh | /bin/bash
#   - project-yamls.zip in the same directory as this script
# =============================================================================

set -euo pipefail

# ---------- colours ---------------------------------------------------------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'

info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
error()   { echo -e "${RED}[ERROR]${RESET} $*" >&2; }
header()  { echo -e "\n${BOLD}======================================================${RESET}"; \
            echo -e "${BOLD}  $*${RESET}"; \
            echo -e "${BOLD}======================================================${RESET}"; }

# ---------- argument validation ---------------------------------------------
if [[ $# -ne 1 ]]; then
    error "Expected exactly 1 argument: the directory containing the 4 PDF files."
    echo ""
    echo "Usage: $0 <pdf_dir>"
    echo "Example: $0 ."
    exit 1
fi

PDF_DIR="$(realpath "$1")"

# ---------- locate project root (directory containing this script) ----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ---------- validate PDF inputs --------------------------------------------
header "Validating inputs"

PDFS=("cis-r1.pdf" "cis-r2.pdf" "cis-r3.pdf" "cis-r4.pdf")
for pdf in "${PDFS[@]}"; do
    full_path="$PDF_DIR/$pdf"
    if [[ ! -f "$full_path" ]]; then
        error "PDF not found: $full_path"
        exit 1
    fi
    success "Found: $full_path"
done

# ---------- validate project-yamls.zip -------------------------------------
YAMLS_ZIP="$SCRIPT_DIR/project-yamls.zip"
if [[ ! -f "$YAMLS_ZIP" ]]; then
    error "project-yamls.zip not found at: $YAMLS_ZIP"
    error "Place project-yamls.zip in the same directory as this script."
    exit 1
fi
success "Found: $YAMLS_ZIP"

# ---------- check kubescape ------------------------------------------------
if ! command -v kubescape &>/dev/null; then
    warn "kubescape not found on PATH — Task-3 scans will fail."
    warn "Install with: curl -s https://raw.githubusercontent.com/kubescape/kubescape/master/install.sh | /bin/bash"
else
    success "kubescape found: $(command -v kubescape)"
fi

# ---------- virtual environment --------------------------------------------
header "Setting up virtual environment"

VENV_DIR="$SCRIPT_DIR/comp5700-venv"

if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating virtual environment at $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
    success "Virtual environment created."
else
    info "Reusing existing virtual environment at $VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
success "Activated: $(which python3)"

# ---------- install dependencies -------------------------------------------
header "Installing dependencies"

REQUIREMENTS="$SCRIPT_DIR/requirements.txt"
if [[ ! -f "$REQUIREMENTS" ]]; then
    error "requirements.txt not found at: $REQUIREMENTS"
    exit 1
fi

pip install --quiet --upgrade pip
pip install --quiet -r "$REQUIREMENTS"
success "All dependencies installed."

# ---------- output dirs ----------------------------------------------------
TASK1_OUT="$SCRIPT_DIR/output/task1"
mkdir -p "$TASK1_OUT"

# =============================================================================
# PHASE 1 — Task 1: Extract each unique PDF once
# We pass each PDF as both arguments to run_task1 so it processes just that
# one document. run_task1 saves one YAML per unique doc name, so passing the
# same PDF twice produces exactly one YAML — the intended behaviour.
# =============================================================================
header "PHASE 1 — Task 1: KDE Extraction (4 PDFs)"

for pdf in "${PDFS[@]}"; do
    stem="${pdf%.pdf}"           # e.g. "cis-r1"
    yaml_out="$TASK1_OUT/${stem}-kdes.yaml"
    full_pdf="$PDF_DIR/$pdf"

    if [[ -f "$yaml_out" ]]; then
        info "Skipping $pdf — YAML already exists: $yaml_out"
        continue
    fi

    info "Extracting KDEs from $pdf ..."
    python3 - <<PYEOF
import sys
sys.path.insert(0, "$SCRIPT_DIR")
from task1_extractor import run_task1
run_task1("$full_pdf", "$full_pdf", output_dir="$TASK1_OUT")
PYEOF

    if [[ ! -f "$yaml_out" ]]; then
        error "Task-1 did not produce expected YAML: $yaml_out"
        exit 1
    fi
    success "Produced: $yaml_out"
done

echo ""
success "Phase 1 complete — all 4 YAMLs ready in $TASK1_OUT/"

# =============================================================================
# PHASE 2 — Tasks 2 & 3: All 9 combinations
# =============================================================================
header "PHASE 2 — Tasks 2 & 3: All 9 input combinations"

# All 9 combinations as "r1 r1", "r1 r2", etc.
COMBINATIONS=(
    "r1 r1"
    "r1 r2"
    "r1 r3"
    "r1 r4"
    "r2 r2"
    "r2 r3"
    "r2 r4"
    "r3 r3"
    "r3 r4"
)

COMBO_NUM=0
TOTAL=${#COMBINATIONS[@]}

for combo in "${COMBINATIONS[@]}"; do
    COMBO_NUM=$((COMBO_NUM + 1))
    read -r a b <<< "$combo"

    YAML1="$TASK1_OUT/cis-${a}-kdes.yaml"
    YAML2="$TASK1_OUT/cis-${b}-kdes.yaml"
    COMBO_LABEL="${a}_vs_${b}"

    TASK2_OUT="$SCRIPT_DIR/output/task2/$COMBO_LABEL"
    TASK3_OUT="$SCRIPT_DIR/output/task3/$COMBO_LABEL"
    mkdir -p "$TASK2_OUT" "$TASK3_OUT"

    # Task-2 output filenames mirror the naming logic in task2_comparator.py
    YAML1_STEM="cis-${a}-kdes"
    YAML2_STEM="cis-${b}-kdes"
    NAME_DIFF_TXT="$TASK2_OUT/name-diff_${YAML1_STEM}_vs_${YAML2_STEM}.txt"
    REQ_DIFF_TXT="$TASK2_OUT/req-diff_${YAML1_STEM}_vs_${YAML2_STEM}.txt"

    echo ""
    echo -e "${BOLD}--- Combination $COMBO_NUM/$TOTAL: cis-${a}.pdf + cis-${b}.pdf ---${RESET}"

    # ---- Task 2 --------------------------------------------------------
    info "Running Task 2 (compare) ..."
    python3 - <<PYEOF
import sys
sys.path.insert(0, "$SCRIPT_DIR")
from task2_comparator import run_task2
run_task2("$YAML1", "$YAML2", output_dir="$TASK2_OUT")
PYEOF

    for txt_file in "$NAME_DIFF_TXT" "$REQ_DIFF_TXT"; do
        if [[ ! -f "$txt_file" ]]; then
            error "Task-2 did not produce: $txt_file"
            exit 1
        fi
        success "Produced: $(basename "$txt_file")"
    done

    # ---- Task 3 --------------------------------------------------------
    info "Running Task 3 (execute) ..."
    python3 - <<PYEOF
import sys
sys.path.insert(0, "$SCRIPT_DIR")
from task3_executor import run_task3
run_task3("$NAME_DIFF_TXT", "$REQ_DIFF_TXT", "$YAMLS_ZIP", output_dir="$TASK3_OUT")
PYEOF

    CSV_OUT="$TASK3_OUT/kubescape_report.csv"
    if [[ ! -f "$CSV_OUT" ]]; then
        error "Task-3 did not produce: $CSV_OUT"
        exit 1
    fi
    success "Produced: kubescape_report.csv"
done

# =============================================================================
# Summary
# =============================================================================
header "Pipeline Complete"

echo ""
echo -e "  ${BOLD}Task 1 YAMLs:${RESET}  output/task1/"
for pdf in "${PDFS[@]}"; do
    stem="${pdf%.pdf}"
    echo "    ${stem}-kdes.yaml"
done

echo ""
echo -e "  ${BOLD}Tasks 2 & 3 (per combination):${RESET}"
for combo in "${COMBINATIONS[@]}"; do
    read -r a b <<< "$combo"
    echo "    output/task2/${a}_vs_${b}/   output/task3/${a}_vs_${b}/"
done

echo ""
success "All tasks completed successfully."