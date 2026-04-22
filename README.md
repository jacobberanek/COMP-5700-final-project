# COMP-5700 Secure Software Process — Course Project

## Team

| Name | Email |
|------|-------|
| *Jacob Beranek* | *jjb0098@auburn.edu* |

**LLM used for Task-1:** `google/gemma-3-1b-it`

---

## Checklist

| Requirement | Location |
|-------------|----------|
| Task-1 source code | `task1_extractor.py` |
| Task-2 source code | `task2_comparator.py` |
| Task-3 source code | `task3_executor.py` |
| All prompts | `PROMPT.md` |
| Task-1 test cases | `test_task1.py` |
| Task-2 test cases | `test_task2.py` |
| Task-3 test cases | `test_task3.py` |
| GitHub Actions workflow | `.github/workflows/tests.yml` |
| GitHub Actions logs | Actions tab on this repo |
| BASH Pipeline runner (Mac/Linux) | `run_pipeline.sh` |
| Dependencies | `requirements.txt` |

---

## Quick Start

### Step 1 — Prerequisites

- **Python 3.9+**
- **kubescape**

  Mac/Linux:
  ```bash
  curl -s https://raw.githubusercontent.com/kubescape/kubescape/master/install.sh | /bin/bash
  ```
  Windows: download from https://github.com/kubescape/kubescape/releases and add to PATH.

### Step 2 — Confirm input files are in the project root

The following files must be in the project root:

```
cis-r1.pdf
cis-r2.pdf
cis-r3.pdf
cis-r4.pdf
project-yamls.zip
```

### Step 3 - Running the full pipeline

**Usage:**
```bash
chmod +x run_pipeline.sh
./run_pipeline.sh  
```

**WSL users:** If you see `/usr/bin/env: 'bash\r': No such file or directory`, run `sed -i 's/\r//' run_pipeline.sh` once before executing the script.

Run once per input combination. The TA should run it 9 times total:
```bash
./run_pipeline.sh cis-r1.pdf cis-r1.pdf
./run_pipeline.sh cis-r1.pdf cis-r2.pdf
./run_pipeline.sh cis-r1.pdf cis-r3.pdf
./run_pipeline.sh cis-r1.pdf cis-r4.pdf
./run_pipeline.sh cis-r2.pdf cis-r2.pdf
./run_pipeline.sh cis-r2.pdf cis-r3.pdf
./run_pipeline.sh cis-r2.pdf cis-r4.pdf
./run_pipeline.sh cis-r3.pdf cis-r3.pdf
./run_pipeline.sh cis-r3.pdf cis-r4.pdf
```

Task-1 results are cached — if a YAML already exists for a given PDF, Gemma will not re-run for it. So running all 9 combinations only requires 4 Gemma extractions total.
```

### Running the test suite only (no PDFs or kubescape needed)

```bash
python3 -m venv comp5700-venv
source comp5700-venv/bin/activate       # Windows: comp5700-venv\Scripts\activate
pip install -r requirements.txt
python -m pytest test_task1.py test_task2.py test_task3.py -v
```

All 13 tests are mocked — the Gemma model and kubescape binary are never called.

---

## CI — GitHub Actions

Every push to this repository automatically runs the full test suite via `.github/workflows/tests.yml`. Logs are visible under the **Actions** tab. All 13 tests must pass.

---

## How the Pipeline Works

The pipeline runs in two phases:

### Phase 1 — Task 1: KDE Extraction (4 runs, one per unique PDF)

`task1_extractor.py` processes each PDF independently:

1. Loads and validates the PDF with PyPDF2, extracting all text.
2. Scans the text for numbered requirements matching `X.Y.Z Ensure/Enable/Minimize...`, filters out TOC ghost entries (requirements that only appear once in the document), and builds a `{number: title}` lookup table.
3. Constructs three prompts from that list — zero-shot, few-shot, and chain-of-thought — and runs each through Gemma-3-1B, which groups the requirements into named categories.
4. Applies a quality check: if the LLM output has less than 50% coverage, too few categories, or one oversized category, it falls back to a deterministic section-based grouping.
5. Picks the best result across the three prompt types and saves it as a YAML file.
6. Saves all raw LLM outputs to multiple `llm_outputs.txt` files.

Output YAML structure:
```yaml
element1:
  name: Audit Logging
  requirements:
    - "2.1.1 Ensure audit logs are enabled"
    - "2.1.2 Ensure audit log retention..."
element2:
  name: RBAC
  requirements:
    - "4.1.1 Restrict cluster-admin..."
```

### Phase 2 — Tasks 2 & 3: All 9 input combinations

Tasks 2 and 3 reuse the four YAMLs from Phase 1. Each combination gets its own output subdirectory so nothing is overwritten.

#### Task 2 — Comparator (`task2_comparator.py`)

Produces two diff reports per combination:

- **Name diff** (`name-diff_X_vs_Y.txt`) — KDE names present in one file but not the other. Writes `NO DIFFERENCES IN REGARDS TO ELEMENT NAMES` if identical.
- **Requirement diff** (`req-diff_X_vs_Y.txt`) — every differing requirement in the format:
  ```
  NAME,ABSENT-IN-<file>,PRESENT-IN-<file>,<requirement or NA>
  ```
  `NA` means the entire KDE is missing from one file. Writes `NO DIFFERENCES IN REGARDS TO ELEMENT REQUIREMENTS` if identical.

A normalization pass neutralizes PDF extraction artifacts before comparison (e.g. `read -only` → `read-only`, double spaces, space before punctuation).

#### Task 3 — Executor (`task3_executor.py`)

1. Scans the diff text for keywords and maps them to Kubescape control IDs using a static lookup table (e.g. `audit log` → `C-0067`, `rbac` → `C-0088`). If no differences exist, all controls are run.
2. Runs `kubescape scan control C-XXXX,C-YYYY ... <yamls>` (or `kubescape scan` for all controls) on the extracted contents of `project-yamls.zip`.
3. Parses the Kubescape JSON output from `summaryDetails.controls.<CTRL_ID>`.
4. Writes `kubescape_report.csv` with columns: `FilePath`, `Severity`, `Control name`, `Failed resources`, `All Resources`, `Compliance score`.

---

## Output Directory Structure

```
output/
├── task1/
│   ├── cis-r1-kdes.yaml
│   ├── cis-r2-kdes.yaml
│   ├── cis-r3-kdes.yaml
│   ├── cis-r4-kdes.yaml
│   └── llm_outputs.txt
├── task2/
│   ├── r1_vs_r1/
│   │   ├── name-diff_cis-r1-kdes_vs_cis-r1-kdes.txt
│   │   └── req-diff_cis-r1-kdes_vs_cis-r1-kdes.txt
│   ├── r1_vs_r2/
│   └── ... (9 combinations total)
└── task3/
    ├── r1_vs_r1/
    │   ├── kubescape_controls.txt
    │   ├── kubescape_results.json
    │   └── kubescape_report.csv
    └── ... (9 combinations total)
```

---

## Known Limitations

- **FilePath column in CSV** — Kubescape's aggregate JSON does not always populate per-resource file paths. Affected rows show `N/A`. This is a tool output limitation, not a bug.
- **Minor extraction artifacts** — Gemma-3-1B occasionally produces mid-word spacing or truncated titles due to PDF text extraction noise. Task-2's normalization pass handles the most common cases; residual mismatches are tolerable given the 1B model's constraints.
- **CPU runtime** — Gemma-3-1B runs in bfloat16 on CPU with 8 threads. Expect 5–15 minutes per PDF on a modern CPU.