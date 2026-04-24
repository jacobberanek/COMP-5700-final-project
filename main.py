"""
main.py  —  COMP-5700 Secure Software Process Project Runner
=============================================================
Cross-platform (Windows / macOS / Linux) entry point.

Usage:
    python main.py <pdf1> <pdf2>

Examples:
    python main.py cis-r1.pdf cis-r1.pdf
    python main.py cis-r1.pdf cis-r2.pdf

Run once per input combination. The TA should run it 9 times total:
    python main.py cis-r1.pdf cis-r1.pdf
    python main.py cis-r1.pdf cis-r2.pdf
    python main.py cis-r1.pdf cis-r3.pdf
    python main.py cis-r1.pdf cis-r4.pdf
    python main.py cis-r2.pdf cis-r2.pdf
    python main.py cis-r2.pdf cis-r3.pdf
    python main.py cis-r2.pdf cis-r4.pdf
    python main.py cis-r3.pdf cis-r3.pdf
    python main.py cis-r3.pdf cis-r4.pdf

Task-1 results are cached — if the YAML for a given PDF already exists,
Gemma will not re-run for that PDF.

Requirements:
    - Python 3.9+
    - pip install -r requirements.txt   (run once before first use)
    - kubescape installed and on your PATH
        Mac/Linux: curl -s https://raw.githubusercontent.com/kubescape/kubescape/master/install.sh | /bin/bash
        Windows:   https://github.com/kubescape/kubescape/releases
    - project-yamls.zip in the same directory as this script
"""

import os
import sys


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def _validate_inputs(pdf1: str, pdf2: str) -> tuple[str, str]:
    """Resolve, validate, and return absolute paths for both PDFs."""
    errors = []

    pdf1 = os.path.abspath(pdf1)
    pdf2 = os.path.abspath(pdf2)

    for path in (pdf1, pdf2):
        if not os.path.isfile(path):
            errors.append(f"  PDF not found: {path}")
        elif not path.lower().endswith(".pdf"):
            errors.append(f"  Not a PDF file: {path}")

    if errors:
        print("[ERROR] Input validation failed:")
        for e in errors:
            print(e)
        sys.exit(1)

    return pdf1, pdf2


def _validate_yamls_zip(script_dir: str) -> str:
    """Confirm project-yamls.zip exists and return its path."""
    zip_path = os.path.join(script_dir, "project-yamls.zip")
    if not os.path.isfile(zip_path):
        print(f"[ERROR] project-yamls.zip not found at: {zip_path}")
        print("        Place project-yamls.zip in the same directory as main.py.")
        sys.exit(1)
    return zip_path


def _check_kubescape():
    """Warn (but don't abort) if kubescape is not on PATH."""
    import shutil
    if shutil.which("kubescape") is None:
        print("[WARN]  kubescape not found on PATH — Task-3 scans will fail.")
        print("        Install: curl -s https://raw.githubusercontent.com/kubescape/kubescape/master/install.sh | /bin/bash")
    else:
        import subprocess
        result = subprocess.run(["kubescape", "version"], capture_output=True, text=True)
        print(f"[OK]    kubescape found: {result.stdout.strip()}")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) != 3:
        print(__doc__)
        print("Usage: python main.py <pdf1> <pdf2>")
        sys.exit(1)

    # ---- Locate script directory and add it to sys.path so imports work ----
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    # ---- Validate inputs ---------------------------------------------------
    pdf1, pdf2 = _validate_inputs(sys.argv[1], sys.argv[2])
    yamls_zip  = _validate_yamls_zip(script_dir)
    _check_kubescape()

    print(f"\n[INFO]  PDF 1:  {pdf1}")
    print(f"[INFO]  PDF 2:  {pdf2}")
    print(f"[INFO]  Output: {os.path.join(script_dir, 'output')}/")

    # ---- Derive stems and output directories --------------------------------
    stem1 = os.path.splitext(os.path.basename(pdf1))[0]   # e.g. "cis-r1"
    stem2 = os.path.splitext(os.path.basename(pdf2))[0]   # e.g. "cis-r2"
    combo = f"{stem1}_vs_{stem2}"

    task1_out = os.path.join(script_dir, "output", "task1")
    task2_out = os.path.join(script_dir, "output", "task2", combo)
    task3_out = os.path.join(script_dir, "output", "task3", combo)

    os.makedirs(task1_out, exist_ok=True)
    os.makedirs(task2_out, exist_ok=True)
    os.makedirs(task3_out, exist_ok=True)

    yaml1 = os.path.join(task1_out, f"{stem1}-kdes.yaml")
    yaml2 = os.path.join(task1_out, f"{stem2}-kdes.yaml")

    # When both PDFs are the same file, yaml2 == yaml1
    if stem1 == stem2:
        yaml2 = yaml1

    name_diff_txt = os.path.join(task2_out, f"name-diff_{stem1}-kdes_vs_{stem2}-kdes.txt")
    req_diff_txt  = os.path.join(task2_out, f"req-diff_{stem1}-kdes_vs_{stem2}-kdes.txt")

    # =========================================================================
    # TASK 1 — KDE Extraction (cached: skipped if YAML already exists)
    # =========================================================================
    print("\n" + "=" * 60)
    print("  TASK 1: KDE Extraction")
    print("=" * 60)

    from task1_extractor import run_task1

    if os.path.isfile(yaml1):
        print(f"[INFO]  Skipping {stem1} — YAML already exists: {yaml1}")
    else:
        print(f"[INFO]  Extracting KDEs from {os.path.basename(pdf1)} ...")
        run_task1(pdf1, pdf1, output_dir=task1_out)
        if not os.path.isfile(yaml1):
            print(f"[ERROR] Task-1 did not produce: {yaml1}")
            sys.exit(1)
        print(f"[OK]    Produced: {yaml1}")

    if stem1 != stem2:
        if os.path.isfile(yaml2):
            print(f"[INFO]  Skipping {stem2} — YAML already exists: {yaml2}")
        else:
            print(f"[INFO]  Extracting KDEs from {os.path.basename(pdf2)} ...")
            run_task1(pdf2, pdf2, output_dir=task1_out)
            if not os.path.isfile(yaml2):
                print(f"[ERROR] Task-1 did not produce: {yaml2}")
                sys.exit(1)
            print(f"[OK]    Produced: {yaml2}")

    # =========================================================================
    # TASK 2 — Comparison
    # =========================================================================
    print("\n" + "=" * 60)
    print("  TASK 2: KDE Comparison")
    print("=" * 60)
    print(f"[INFO]  YAML 1: {yaml1}")
    print(f"[INFO]  YAML 2: {yaml2}")

    from task2_comparator import run_task2
    run_task2(yaml1, yaml2, output_dir=task2_out)

    for txt_path in (name_diff_txt, req_diff_txt):
        if not os.path.isfile(txt_path):
            print(f"[ERROR] Task-2 did not produce: {txt_path}")
            sys.exit(1)
        print(f"[OK]    Produced: {os.path.basename(txt_path)}")

    # =========================================================================
    # TASK 3 — Kubescape Execution
    # =========================================================================
    print("\n" + "=" * 60)
    print("  TASK 3: Kubescape Execution")
    print("=" * 60)

    from task3_executor import run_task3
    run_task3(name_diff_txt, req_diff_txt, yamls_zip, output_dir=task3_out)

    csv_path = os.path.join(task3_out, "kubescape_report.csv")
    if not os.path.isfile(csv_path):
        print(f"[ERROR] Task-3 did not produce: {csv_path}")
        sys.exit(1)

    # =========================================================================
    # Summary
    # =========================================================================
    print("\n" + "=" * 60)
    print("  PIPELINE COMPLETE")
    print("=" * 60)
    print(f"\n  Input:   {os.path.basename(pdf1)}  +  {os.path.basename(pdf2)}")
    print(f"  Task 1:  {task1_out}/")
    print(f"  Task 2:  {task2_out}/")
    print(f"  Task 3:  {task3_out}/")
    print("\n[OK]    Done.")


if __name__ == "__main__":
    main()