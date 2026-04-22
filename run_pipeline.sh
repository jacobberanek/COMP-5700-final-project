#!/usr/bin/env bash
# =============================================================================
# run_pipeline.sh  —  COMP-5700 Secure Software Process Project Runner
#
# Usage:
#   ./run_pipeline.sh <pdf1> <pdf2>
#
# Examples:
#   ./run_pipeline.sh cis-r1.pdf cis-r1.pdf
#   ./run_pipeline.sh cis-r1.pdf cis-r2.pdf
#
# Run once per input combination. The TA should run it 9 times total:
#   ./run_pipeline.sh cis-r1.pdf cis-r1.pdf
#   ./run_pipeline.sh cis-r1.pdf cis-r2.pdf
#   ./run_pipeline.sh cis-r1.pdf cis-r3.pdf
#   ./run_pipeline.sh cis-r1.pdf cis-r4.pdf
#   ./run_pipeline.sh cis-r2.pdf cis-r2.pdf
#   ./run_pipeline.sh cis-r2.pdf cis-r3.pdf
#   ./run_pipeline.sh cis-r2.pdf cis-r4.pdf
#   ./run_pipeline.sh cis-r3.pdf cis-r3.pdf
#   ./run_pipeline.sh cis-r3.pdf cis-r4.pdf
#
# Task-1 results are cached — if a YAML already exists for a given PDF,
# Gemma will not re-run for that PDF.
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
if [[ $# -ne 2 ]]; then
    error "Expected exactly 2 arguments: two PDF file paths."
    echo ""
    echo "Usage: $0 <pdf1> <pdf2>"
    echo ""
    echo "Examples:"
    echo "  $0 cis-r1.pdf cis-r1.pdf"
    echo "  $0 cis-r1.pdf cis-r2.pdf"
    echo "  $0 cis-r2.pdf cis-r3.pdf"
    exit 1
fi

PDF1_POSIX="$(realpath "$1")"
PDF2_POSIX="$(realpath "$2")"

# ---------- locate project root (directory containing this script) ----------
SCRIPT_DIR_POSIX="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR_POSIX"

# ---------- convert POSIX paths to Windows paths for Python on Windows ------
# Git Bash uses /c/Users/... but Windows Python needs C:\Users\...
# cygpath is available in Git Bash; on true Linux/Mac this block is skipped.
if command -v cygpath &>/dev/null; then
    PDF1="$(cygpath -m "$PDF1_POSIX")"
    PDF2="$(cygpath -m "$PDF2_POSIX")"
    SCRIPT_DIR="$(cygpath -m "$SCRIPT_DIR_POSIX")"
else
    PDF1="$PDF1_POSIX"
    PDF2="$PDF2_POSIX"
    SCRIPT_DIR="$SCRIPT_DIR_POSIX"
fi

# ---------- validate PDF inputs --------------------------------------------
header "Validating inputs"

for pdf in "$PDF1_POSIX" "$PDF2_POSIX"; do
    if [[ ! -f "$pdf" ]]; then
        error "PDF not found: $pdf"
        exit 1
    fi
    if [[ "${pdf##*.}" != "pdf" && "${pdf##*.}" != "PDF" ]]; then
        error "Not a PDF file: $pdf"
        exit 1
    fi
    success "Found: $pdf"
done

# ---------- validate project-yamls.zip -------------------------------------
YAMLS_ZIP_POSIX="$SCRIPT_DIR_POSIX/project-yamls.zip"
if command -v cygpath &>/dev/null; then
    YAMLS_ZIP="$(cygpath -m "$YAMLS_ZIP_POSIX")"
else
    YAMLS_ZIP="$YAMLS_ZIP_POSIX"
fi
if [[ ! -f "$YAMLS_ZIP_POSIX" ]]; then
    error "project-yamls.zip not found at: $YAMLS_ZIP_POSIX"
    error "Place project-yamls.zip in the same directory as this script."
    exit 1
fi
success "Found: $YAMLS_ZIP_POSIX"

# ---------- check kubescape ------------------------------------------------
if ! command -v kubescape &>/dev/null; then
    warn "kubescape not found on PATH — Task-3 scans will fail."
    warn "Install: curl -s https://raw.githubusercontent.com/kubescape/kubescape/master/install.sh | /bin/bash"
else
    success "kubescape found: $(command -v kubescape)"
fi

# ---------- virtual environment --------------------------------------------
header "Setting up virtual environment"

VENV_DIR_POSIX="$SCRIPT_DIR_POSIX/comp5700-venv"

if [[ ! -d "$VENV_DIR_POSIX" ]]; then
    info "Creating virtual environment at $VENV_DIR_POSIX ..."
    python3 -m venv "$VENV_DIR_POSIX"
    success "Virtual environment created."
else
    info "Reusing existing virtual environment at $VENV_DIR_POSIX"
fi

# Resolve the venv python binary directly — used for all python calls below.
# This avoids heredoc subshells not inheriting the activated venv.
if [[ -f "$VENV_DIR_POSIX/bin/python3" ]]; then
    VENV_PYTHON="$VENV_DIR_POSIX/bin/python3"
elif [[ -f "$VENV_DIR_POSIX/bin/python" ]]; then
    VENV_PYTHON="$VENV_DIR_POSIX/bin/python"
elif [[ -f "$VENV_DIR_POSIX/Scripts/python.exe" ]]; then
    VENV_PYTHON="$VENV_DIR_POSIX/Scripts/python.exe"
else
    error "Could not find python binary in venv at $VENV_DIR_POSIX"
    exit 1
fi

success "Using python: $VENV_PYTHON"

# ---------- install dependencies -------------------------------------------
header "Installing dependencies"

REQUIREMENTS="$SCRIPT_DIR_POSIX/requirements.txt"
if [[ ! -f "$REQUIREMENTS" ]]; then
    error "requirements.txt not found at: $REQUIREMENTS"
    exit 1
fi

"$VENV_PYTHON" -m pip install --quiet -r "$REQUIREMENTS"
success "All dependencies installed."

# ---------- derive stems and output paths ----------------------------------
STEM1="$(basename "$PDF1_POSIX" .pdf)"
STEM2="$(basename "$PDF2_POSIX" .pdf)"
COMBO_LABEL="${STEM1}_vs_${STEM2}"

TASK1_OUT_POSIX="$SCRIPT_DIR_POSIX/output/task1"
TASK2_OUT_POSIX="$SCRIPT_DIR_POSIX/output/task2/$COMBO_LABEL"
TASK3_OUT_POSIX="$SCRIPT_DIR_POSIX/output/task3/$COMBO_LABEL"

mkdir -p "$TASK1_OUT_POSIX" "$TASK2_OUT_POSIX" "$TASK3_OUT_POSIX"

# Windows-style paths for Python heredocs
if command -v cygpath &>/dev/null; then
    TASK1_OUT="$(cygpath -m "$TASK1_OUT_POSIX")"
    TASK2_OUT="$(cygpath -m "$TASK2_OUT_POSIX")"
    TASK3_OUT="$(cygpath -m "$TASK3_OUT_POSIX")"
else
    TASK1_OUT="$TASK1_OUT_POSIX"
    TASK2_OUT="$TASK2_OUT_POSIX"
    TASK3_OUT="$TASK3_OUT_POSIX"
fi

YAML1_POSIX="$TASK1_OUT_POSIX/${STEM1}-kdes.yaml"
YAML2_POSIX="$TASK1_OUT_POSIX/${STEM2}-kdes.yaml"

if [[ "$STEM1" == "$STEM2" ]]; then
    YAML2_POSIX="$YAML1_POSIX"
fi

if command -v cygpath &>/dev/null; then
    YAML1="$(cygpath -m "$YAML1_POSIX")"
    YAML2="$(cygpath -m "$YAML2_POSIX")"
else
    YAML1="$YAML1_POSIX"
    YAML2="$YAML2_POSIX"
fi

NAME_DIFF_TXT_POSIX="$TASK2_OUT_POSIX/name-diff_${STEM1}-kdes_vs_${STEM2}-kdes.txt"
REQ_DIFF_TXT_POSIX="$TASK2_OUT_POSIX/req-diff_${STEM1}-kdes_vs_${STEM2}-kdes.txt"

if command -v cygpath &>/dev/null; then
    NAME_DIFF_TXT="$(cygpath -m "$NAME_DIFF_TXT_POSIX")"
    REQ_DIFF_TXT="$(cygpath -m "$REQ_DIFF_TXT_POSIX")"
else
    NAME_DIFF_TXT="$NAME_DIFF_TXT_POSIX"
    REQ_DIFF_TXT="$REQ_DIFF_TXT_POSIX"
fi

# =============================================================================
# TASK 1 — KDE Extraction (skipped if YAML already exists)
# =============================================================================
header "Task 1: KDE Extraction"
info "PDF 1: $PDF1"
info "PDF 2: $PDF2"

if [[ -f "$YAML1_POSIX" ]]; then
    info "Skipping $STEM1 — YAML already exists: $YAML1_POSIX"
else
    info "Extracting KDEs from $(basename "$PDF1_POSIX") ..."
    PIPELINE_SCRIPT_DIR="$SCRIPT_DIR" \
    PIPELINE_PDF="$PDF1" \
    PIPELINE_OUT="$TASK1_OUT" \
    "$VENV_PYTHON" - <<'PYEOF'
import sys, os
sys.path.insert(0, os.environ["PIPELINE_SCRIPT_DIR"])
from task1_extractor import run_task1
run_task1(os.environ["PIPELINE_PDF"], os.environ["PIPELINE_PDF"], output_dir=os.environ["PIPELINE_OUT"])
PYEOF
    if [[ ! -f "$YAML1_POSIX" ]]; then
        error "Task-1 did not produce: $YAML1_POSIX"
        exit 1
    fi
    success "Produced: $YAML1_POSIX"
fi

if [[ "$STEM1" != "$STEM2" ]]; then
    if [[ -f "$YAML2_POSIX" ]]; then
        info "Skipping $STEM2 — YAML already exists: $YAML2_POSIX"
    else
        info "Extracting KDEs from $(basename "$PDF2_POSIX") ..."
        PIPELINE_SCRIPT_DIR="$SCRIPT_DIR" \
        PIPELINE_PDF="$PDF2" \
        PIPELINE_OUT="$TASK1_OUT" \
        "$VENV_PYTHON" - <<'PYEOF'
import sys, os
sys.path.insert(0, os.environ["PIPELINE_SCRIPT_DIR"])
from task1_extractor import run_task1
run_task1(os.environ["PIPELINE_PDF"], os.environ["PIPELINE_PDF"], output_dir=os.environ["PIPELINE_OUT"])
PYEOF
        if [[ ! -f "$YAML2_POSIX" ]]; then
            error "Task-1 did not produce: $YAML2_POSIX"
            exit 1
        fi
        success "Produced: $YAML2_POSIX"
    fi
fi

# =============================================================================
# TASK 2 — Comparison
# =============================================================================
header "Task 2: KDE Comparison"
info "YAML 1: $YAML1"
info "YAML 2: $YAML2"

PIPELINE_SCRIPT_DIR="$SCRIPT_DIR" \
PIPELINE_YAML1="$YAML1" \
PIPELINE_YAML2="$YAML2" \
PIPELINE_OUT="$TASK2_OUT" \
"$VENV_PYTHON" - <<'PYEOF'
import sys, os
sys.path.insert(0, os.environ["PIPELINE_SCRIPT_DIR"])
from task2_comparator import run_task2
run_task2(os.environ["PIPELINE_YAML1"], os.environ["PIPELINE_YAML2"], output_dir=os.environ["PIPELINE_OUT"])
PYEOF

for txt_file in "$NAME_DIFF_TXT_POSIX" "$REQ_DIFF_TXT_POSIX"; do
    if [[ ! -f "$txt_file" ]]; then
        error "Task-2 did not produce: $txt_file"
        exit 1
    fi
    success "Produced: $(basename "$txt_file")"
done

# =============================================================================
# TASK 3 — Execution
# =============================================================================
header "Task 3: Kubescape Execution"

PIPELINE_SCRIPT_DIR="$SCRIPT_DIR" \
PIPELINE_TXT1="$NAME_DIFF_TXT" \
PIPELINE_TXT2="$REQ_DIFF_TXT" \
PIPELINE_ZIP="$YAMLS_ZIP" \
PIPELINE_OUT="$TASK3_OUT" \
"$VENV_PYTHON" - <<'PYEOF'
import sys, os
sys.path.insert(0, os.environ["PIPELINE_SCRIPT_DIR"])
from task3_executor import run_task3
run_task3(os.environ["PIPELINE_TXT1"], os.environ["PIPELINE_TXT2"], os.environ["PIPELINE_ZIP"], output_dir=os.environ["PIPELINE_OUT"])
PYEOF

CSV_OUT_POSIX="$TASK3_OUT_POSIX/kubescape_report.csv"
if [[ ! -f "$CSV_OUT_POSIX" ]]; then
    error "Task-3 did not produce: $CSV_OUT_POSIX"
    exit 1
fi
success "Produced: $CSV_OUT_POSIX"

# =============================================================================
# Summary
# =============================================================================
header "Pipeline Complete"

echo ""
echo -e "  ${BOLD}Input:${RESET}   $(basename "$PDF1_POSIX")  +  $(basename "$PDF2_POSIX")"
echo -e "  ${BOLD}Task 1:${RESET}  $TASK1_OUT_POSIX/"
echo -e "  ${BOLD}Task 2:${RESET}  $TASK2_OUT_POSIX/"
echo -e "  ${BOLD}Task 3:${RESET}  $TASK3_OUT_POSIX/"
echo ""
success "Done."