"""
Task-3: Executor
Reads Task-2 diff files, maps differences to Kubescape controls,
executes Kubescape on project-yamls.zip, and outputs a CSV report.
"""

import os
import sys
import json
import zipfile
import tempfile
import subprocess
import pandas as pd


# ===== Keyword -> Kubescape control mapping ================================
# Based on KDE names seen in CIS EKS benchmark outputs and the Kubescape
# control library at https://kubescape.io/docs/controls/

KEYWORD_CONTROL_MAP = [
    # (list of keywords that must ALL appear, control_id, control_name)
    (["privileged container"],          "C-0057", "Privileged container"),
    (["privilege escalation"],          "C-0016", "Allow privilege escalation"),
    (["non-root", "root container"],    "C-0013", "Non-root containers"),
    (["host pid", "host process id"],   "C-0038", "Host PID/IPC privileges"),
    (["host ipc"],                      "C-0038", "Host PID/IPC privileges"),
    (["host network"],                  "C-0041", "HostNetwork access"),
    (["network policy"],                "C-0030", "Ingress and Egress blocked"),
    (["secret"],                        "C-0015", "List Kubernetes secrets"),
    (["secret encrypt", "encrypt"],     "C-0066", "Secret/etcd encryption enabled"),
    (["audit log"],                     "C-0067", "Audit logs enabled"),
    (["rbac", "cluster-admin",
      "administrative"],               "C-0035", "Administrative Roles"),
    (["rbac"],                          "C-0088", "RBAC enabled"),
    (["anonymous"],                     "C-0069", "Disable anonymous access to Kubelet service"),
    (["kubelet", "tls", "client ca"],   "C-0070", "Enforce Kubelet client TLS authentication"),
    (["security context"],              "C-0055", "Linux hardening"),
    (["capabilities"],                  "C-0046", "Insecure capabilities"),
    (["namespace"],                     "C-0061", "Pods in default namespace"),
    (["service account"],               "C-0053", "Access container service account"),
    (["image", "vulnerability",
      "scanning"],                      "C-0085", "Workloads with excessive amount of vulnerabilities"),
    (["image", "registry"],             "C-0078", "Images from allowed registry"),
    (["read-only port", "readonly"],    "C-0069", "Disable anonymous access to Kubelet service"),
    (["rotate", "certificate"],         "C-0070", "Enforce Kubelet client TLS authentication"),
    (["admission"],                     "C-0036", "Validate admission controller (validating)"),
    (["psp", "podsecurity"],            "C-0068", "PSP enabled"),
    (["fargate", "untrusted workload"], "C-0057", "Privileged container"),
    (["iptables"],                      "C-0041", "HostNetwork access"),
    (["authorization", "alwaysallow"],  "C-0088", "RBAC enabled"),
]


# ===== Function 1: Load Task-2 TEXT files =================================

def load_diff_files(txt_path1: str, txt_path2: str) -> tuple[str, str]:
    """
    Takes two TEXT file paths from Task-2, validates and returns their content.
    Raises ValueError / FileNotFoundError on invalid input.
    """
    contents = []
    for path in (txt_path1, txt_path2):
        if not isinstance(path, str) or not path.strip():
            raise ValueError(f"Invalid path: {path!r}")
        if not os.path.isfile(path):
            raise FileNotFoundError(f"File not found: {path}")
        if not path.lower().endswith(".txt"):
            raise ValueError(f"Not a TEXT file: {path}")
        with open(path, "r", encoding="utf-8") as f:
            contents.append(f.read())

    return contents[0], contents[1]


# ===== Function 2: Map differences to Kubescape controls ==================

def map_to_controls(content1: str, content2: str, output_dir: str = ".") -> str:
    """
    Reads Task-2 diff file contents and maps differences to Kubescape controls
    using keyword matching. Writes a TEXT file and returns its path.

    Output is either:
      - 'NO DIFFERENCES FOUND'  (if both files have no differences)
      - One control ID per line  (e.g. C-0057, C-0016, ...)
    """
    no_diff_markers = [
        "NO DIFFERENCES IN REGARDS TO ELEMENT NAMES",
        "NO DIFFERENCES IN REGARDS TO ELEMENT REQUIREMENTS",
        "NO DIFFERENCES FOUND",
    ]

    def _has_differences(content: str) -> bool:
        for marker in no_diff_markers:
            if marker in content:
                return False
        # Also treat empty/whitespace-only as no differences
        return bool(content.strip())

    has_diff = _has_differences(content1) or _has_differences(content2)

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "kubescape_controls.txt")

    if not has_diff:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("NO DIFFERENCES FOUND\n")
        print(f"  [map_to_controls] No differences -> {out_path}")
        return out_path

    # Collect all KDE names and requirement text from both diff files
    combined = (content1 + "\n" + content2).lower()

    matched = {}  # control_id -> control_name (deduplicated)
    for keywords, ctrl_id, ctrl_name in KEYWORD_CONTROL_MAP:
        if all(kw in combined for kw in keywords):
            matched[ctrl_id] = ctrl_name

    with open(out_path, "w", encoding="utf-8") as f:
        if not matched:
            f.write("NO DIFFERENCES FOUND\n")
        else:
            for ctrl_id, ctrl_name in sorted(matched.items()):
                f.write(f"{ctrl_id} {ctrl_name}\n")

    print(f"  [map_to_controls] {len(matched)} controls mapped -> {out_path}")
    return out_path


# ===== Function 3: Execute Kubescape ======================================

def execute_kubescape(controls_txt_path: str, yamls_zip_path: str,
                      output_dir: str = ".") -> pd.DataFrame:
    """
    Runs Kubescape on the extracted YAML files from yamls_zip_path.
    Reads controls_txt_path to decide which controls to run.
    Returns a pandas DataFrame with scan results.
    """
    # Read controls file
    with open(controls_txt_path, "r", encoding="utf-8") as f:
        content = f.read().strip()

    run_all = (content == "NO DIFFERENCES FOUND")

    # Extract control IDs (e.g. C-0057)
    import re
    control_ids = re.findall(r"C-\d{4}", content) if not run_all else []

    # Extract zip to a temp directory
    tmp_dir = tempfile.mkdtemp(prefix="kubescape_yamls_")
    with zipfile.ZipFile(yamls_zip_path, "r") as zf:
        zf.extractall(tmp_dir)
    print(f"  [execute_kubescape] Extracted YAMLs to {tmp_dir}")

    # Build kubescape command
    json_out = os.path.join(output_dir, "kubescape_results.json")
    os.makedirs(output_dir, exist_ok=True)

    if run_all:
        cmd = [
            "kubescape", "scan",
            "--format", "json",
            "--output", json_out,
            tmp_dir,
        ]
        print(f"  [execute_kubescape] Running all controls on {tmp_dir}")
    else:
        controls_arg = ",".join(control_ids)
        cmd = [
            "kubescape", "scan", "control", controls_arg,
            "--format", "json",
            "--output", json_out,
            tmp_dir,
        ]
        print(f"  [execute_kubescape] Running controls: {controls_arg}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        print(f"  [execute_kubescape] Exit code: {result.returncode}")
        if result.stdout:
            print(f"  [execute_kubescape] stdout: {result.stdout[:500]}")
        if result.stderr:
            print(f"  [execute_kubescape] stderr: {result.stderr[:300]}")
    except FileNotFoundError:
        raise RuntimeError(
            "Kubescape not found. Install it with: "
            "curl -s https://raw.githubusercontent.com/kubescape/kubescape/master/install.sh | /bin/bash"
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("Kubescape scan timed out after 300 seconds")

    # Parse JSON output into DataFrame
    df = _parse_kubescape_json(json_out)
    print(f"  [execute_kubescape] DataFrame: {len(df)} rows")
    return df


# ===== Function 4: Generate CSV ===========================================

def generate_csv(df: pd.DataFrame, output_dir: str = ".") -> str:
    """
    Takes the DataFrame from execute_kubescape and writes a CSV file
    with headers: FilePath, Severity, Control name, Failed resources,
    All Resources, Compliance score.
    Returns the path to the CSV file.
    """
    required_cols = [
        "FilePath", "Severity", "Control name",
        "Failed resources", "All Resources", "Compliance score"
    ]

    # Ensure all required columns exist
    for col in required_cols:
        if col not in df.columns:
            df[col] = "N/A"

    os.makedirs(output_dir, exist_ok=True)
    csv_path = os.path.join(output_dir, "kubescape_report.csv")
    df[required_cols].to_csv(csv_path, index=False)
    print(f"  [generate_csv] CSV written -> {csv_path} ({len(df)} rows)")
    return csv_path


# ===== Internal helpers ===================================================

def _parse_kubescape_json(json_path: str) -> pd.DataFrame:
    """
    Parse Kubescape JSON output into a DataFrame with the required columns.
    Actual structure: summaryDetails.controls.<CTRL_ID> -> control dict
    resourceIDs is a dict {resourceID: status}; filepath lookup from top-level resources list.
    """
    if not os.path.isfile(json_path):
        print(f"  [_parse_kubescape_json] JSON file not found: {json_path}")
        return _empty_dataframe()

    with open(json_path, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"  [_parse_kubescape_json] JSON parse error: {e}")
            return _empty_dataframe()

    # Build resourceID -> filepath lookup from top-level resources list
    resource_path_map = {}
    for res in data.get("resources", []):
        rid = res.get("resourceID", "")
        source = res.get("source") or {}
        path = source.get("relativePath", "") or source.get("path", "")
        if rid and path:
            resource_path_map[rid] = path

    controls = data.get("summaryDetails", {}).get("controls", {})
    if not controls:
        print(f"  [_parse_kubescape_json] No controls found in summaryDetails")
        return _empty_dataframe()

    rows = []
    for ctrl_id, control in controls.items():
        ctrl_name = control.get("name", ctrl_id)
        severity = control.get("severity", _score_to_severity(control.get("scoreFactor", 0)))

        counters = control.get("ResourceCounters", {})
        failed  = counters.get("failedResources", 0)
        passed  = counters.get("passedResources", 0)
        skipped = counters.get("skippedResources", 0)
        total   = failed + passed + skipped

        raw_score = control.get("complianceScore", None)
        score = f"{raw_score:.1f}%" if raw_score is not None else _compute_compliance(failed, total)

        # resourceIDs is a dict {resourceID: status} in this Kubescape version
        resource_ids = control.get("resourceIDs", {})
        if isinstance(resource_ids, dict) and resource_ids:
            for rid in resource_ids.keys():
                filepath = resource_path_map.get(rid, rid)
                rows.append({
                    "FilePath": filepath,
                    "Severity": severity,
                    "Control name": ctrl_name,
                    "Failed resources": failed,
                    "All Resources": total,
                    "Compliance score": score,
                })
        else:
            rows.append({
                "FilePath": "N/A",
                "Severity": severity,
                "Control name": ctrl_name,
                "Failed resources": failed,
                "All Resources": total,
                "Compliance score": score,
            })

    print(f"  [_parse_kubescape_json] Parsed {len(controls)} controls, {len(rows)} rows")
    return pd.DataFrame(rows) if rows else _empty_dataframe()


def _extract_severity(control: dict) -> str:
    """Extract severity string from a control dict."""
    # Kubescape stores severity as scoreFactor or as a nested object
    score_factor = control.get("scoreFactor", 0)
    severity_map = control.get("severity", {})
    if isinstance(severity_map, dict):
        return severity_map.get("severity", _score_to_severity(score_factor))
    if isinstance(severity_map, str):
        return severity_map
    return _score_to_severity(score_factor)


def _score_to_severity(score: float) -> str:
    if score >= 7:
        return "High"
    elif score >= 4:
        return "Medium"
    elif score > 0:
        return "Low"
    return "Unknown"


def _compute_compliance(failed: int, total: int) -> str:
    if total == 0:
        return "N/A"
    passed = total - failed
    pct = (passed / total) * 100
    return f"{pct:.1f}%"


def _empty_dataframe() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "FilePath", "Severity", "Control name",
        "Failed resources", "All Resources", "Compliance score"
    ])


# ===== Main entry point ===================================================

def run_task3(txt1: str, txt2: str, yamls_zip: str, output_dir: str = "output/task3"):
    """Run the full Task-3 pipeline."""
    os.makedirs(output_dir, exist_ok=True)

    print("\n" + "#" * 60)
    print("  TASK 3: EXECUTOR")
    print(f"  Diff file 1: {os.path.basename(txt1)}")
    print(f"  Diff file 2: {os.path.basename(txt2)}")
    print(f"  YAMLs zip:   {os.path.basename(yamls_zip)}")
    print(f"  Output:      {output_dir}/")
    print("#" * 60)

    print("\n>> STEP 1/4: Loading Task-2 diff files")
    content1, content2 = load_diff_files(txt1, txt2)
    print(f"  Loaded {os.path.basename(txt1)} ({len(content1)} chars)")
    print(f"  Loaded {os.path.basename(txt2)} ({len(content2)} chars)")

    print("\n>> STEP 2/4: Mapping differences to Kubescape controls")
    controls_path = map_to_controls(content1, content2, output_dir)

    print("\n>> STEP 3/4: Executing Kubescape")
    df = execute_kubescape(controls_path, yamls_zip, output_dir)

    print("\n>> STEP 4/4: Generating CSV report")
    csv_path = generate_csv(df, output_dir)

    print("\n" + "#" * 60)
    print("  TASK 3 COMPLETE")
    print(f"  Controls file: {controls_path}")
    print(f"  CSV report:    {csv_path}")
    print(f"  Rows in report: {len(df)}")
    print("#" * 60 + "\n")

    return controls_path, df, csv_path


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    task2_dir = os.path.join(base_dir, "output", "task2")
    task3_dir = os.path.join(base_dir, "output", "task3")

    if len(sys.argv) == 4:
        t1, t2, zp = sys.argv[1], sys.argv[2], sys.argv[3]
    else:
        t1 = os.path.join(task2_dir, "name-diff_cis-r1-kdes_vs_cis-r2-kdes.txt")
        t2 = os.path.join(task2_dir, "req-diff_cis-r1-kdes_vs_cis-r2-kdes.txt")
        zp = os.path.join(base_dir, "project-yamls.zip")

    run_task3(t1, t2, zp, output_dir=task3_dir)