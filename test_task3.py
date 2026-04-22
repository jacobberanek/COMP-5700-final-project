"""
Test cases for Task-3: Executor
One test per function as specified in the README.
Run with: python -m pytest test_task3.py -v
"""

import os
import csv
import json
import zipfile
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock

from task3_executor import (
    load_diff_files,
    map_to_controls,
    execute_kubescape,
    generate_csv,
)

# Diff content with keywords that match known Kubescape controls
DIFF_WITH_DIFFERENCES = (
    "Audit Logging,ABSENT-IN-cis-r2-kdes.yaml,PRESENT-IN-cis-r1-kdes.yaml,"
    "2.1.1 Ensure audit logs are enabled\n"
    "RBAC,ABSENT-IN-cis-r2-kdes.yaml,PRESENT-IN-cis-r1-kdes.yaml,"
    "4.1.1 Restrict cluster-admin role usage\n"
)

DIFF_NO_DIFFERENCES = "NO DIFFERENCES IN REGARDS TO ELEMENT REQUIREMENTS\n"


def _write_txt(tmp_path, filename, content):
    path = os.path.join(tmp_path, filename)
    with open(path, "w") as f:
        f.write(content)
    return path


def _make_zip(tmp_path):
    yaml_path = os.path.join(tmp_path, "dummy.yaml")
    with open(yaml_path, "w") as f:
        f.write("apiVersion: v1\nkind: Pod\n")
    zip_path = os.path.join(tmp_path, "project-yamls.zip")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(yaml_path, "dummy.yaml")
    return zip_path


def _make_kubescape_json(tmp_path):
    """Write a minimal Kubescape JSON result file matching the real schema."""
    data = {
        "resources": [],
        "summaryDetails": {
            "controls": {
                "C-0067": {
                    "name": "Audit logs enabled",
                    "scoreFactor": 8,
                    "complianceScore": 0.0,
                    "ResourceCounters": {
                        "failedResources": 1,
                        "passedResources": 0,
                        "skippedResources": 0,
                    },
                    "resourceIDs": {},
                }
            }
        },
    }
    path = os.path.join(tmp_path, "kubescape_results.json")
    with open(path, "w") as f:
        json.dump(data, f)
    return path


# ===== Test 1: load_diff_files ============================================

def test_load_diff_files(tmp_path):
    """load_diff_files must return the exact content of both text files."""
    p1 = _write_txt(str(tmp_path), "name-diff.txt", DIFF_WITH_DIFFERENCES)
    p2 = _write_txt(str(tmp_path), "req-diff.txt", DIFF_NO_DIFFERENCES)

    c1, c2 = load_diff_files(p1, p2)

    assert c1 == DIFF_WITH_DIFFERENCES
    assert c2 == DIFF_NO_DIFFERENCES


# ===== Test 2: map_to_controls ============================================

def test_map_to_controls(tmp_path):
    """map_to_controls must map diff keywords to the correct Kubescape control IDs."""
    out_path = map_to_controls(
        DIFF_WITH_DIFFERENCES, DIFF_WITH_DIFFERENCES, str(tmp_path)
    )

    content = open(out_path).read()
    assert "C-0067" in content   # "audit log" keyword
    assert "C-0088" in content   # "rbac" keyword
    assert "NO DIFFERENCES FOUND" not in content


# ===== Test 3: execute_kubescape (subprocess mocked) =====================

def test_execute_kubescape(tmp_path):
    """execute_kubescape must return a DataFrame with all six required columns."""
    controls_txt = _write_txt(
        str(tmp_path), "kubescape_controls.txt", "C-0067 Audit logs enabled\n"
    )
    zip_path = _make_zip(str(tmp_path))
    _make_kubescape_json(str(tmp_path))

    def fake_run(cmd, **kwargs):
        r = MagicMock()
        r.returncode = 0
        r.stdout = r.stderr = ""
        return r

    with patch("task3_executor.subprocess.run", side_effect=fake_run):
        df = execute_kubescape(controls_txt, zip_path, output_dir=str(tmp_path))

    required_cols = [
        "FilePath", "Severity", "Control name",
        "Failed resources", "All Resources", "Compliance score",
    ]
    assert isinstance(df, pd.DataFrame)
    for col in required_cols:
        assert col in df.columns


# ===== Test 4: generate_csv ===============================================

def test_generate_csv(tmp_path):
    """generate_csv must write a CSV whose headers match the six required columns."""
    df = pd.DataFrame([{
        "FilePath": "dummy.yaml",
        "Severity": "High",
        "Control name": "Audit logs enabled",
        "Failed resources": 1,
        "All Resources": 1,
        "Compliance score": "0.0%",
    }])
    csv_path = generate_csv(df, str(tmp_path))

    assert os.path.isfile(csv_path)
    with open(csv_path, newline="") as f:
        headers = csv.DictReader(f).fieldnames

    assert headers == [
        "FilePath", "Severity", "Control name",
        "Failed resources", "All Resources", "Compliance score",
    ]