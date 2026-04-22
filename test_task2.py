"""
Test cases for Task-2: Comparator
One test per function as specified in the README.
Run with: python -m pytest test_task2_comparator.py -v
"""

import os
import yaml
import pytest
import tempfile

from task2_comparator import load_yaml_files, compare_kde_names, compare_kde_requirements


# ===== Fixtures ===========================================================

def _write_yaml(tmp_path, filename: str, data: dict) -> str:
    path = os.path.join(tmp_path, filename)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)
    return path


YAML_A = {
    "element1": {"name": "Audit Logging",     "requirements": ["2.1.1 Enable audit logs", "2.1.2 Retain logs 90 days"]},
    "element2": {"name": "RBAC",              "requirements": ["4.1.1 Restrict cluster-admin", "4.1.2 Minimize secrets access"]},
    "element3": {"name": "Network Policies",  "requirements": ["5.3.1 Create network policies", "5.3.2 Default deny"]},
}

YAML_B = {
    "element1": {"name": "Audit Logging",     "requirements": ["2.1.1 Enable audit logs"]},   # missing 2.1.2
    "element2": {"name": "RBAC",              "requirements": ["4.1.1 Restrict cluster-admin", "4.1.3 Minimize wildcard use"]},  # req diff
    "element3": {"name": "Pod Security",      "requirements": ["4.2.1 Restrict privileged containers"]},  # different name
}

YAML_IDENTICAL = {
    "element1": {"name": "Audit Logging", "requirements": ["2.1.1 Enable audit logs"]},
}


# ===== Test 1: load_yaml_files ============================================

class TestLoadYamlFiles:
    def test_loads_two_valid_yaml_files(self, tmp_path):
        """Function must load two valid YAML files and return their dicts."""
        p1 = _write_yaml(str(tmp_path), "a.yaml", YAML_A)
        p2 = _write_yaml(str(tmp_path), "b.yaml", YAML_B)

        d1, d2 = load_yaml_files(p1, p2)

        assert isinstance(d1, dict)
        assert isinstance(d2, dict)
        assert len(d1) == 3
        assert len(d2) == 3
        assert d1["element1"]["name"] == "Audit Logging"

    def test_raises_on_missing_file(self, tmp_path):
        p1 = _write_yaml(str(tmp_path), "a.yaml", YAML_A)
        with pytest.raises(FileNotFoundError):
            load_yaml_files(p1, "/nonexistent/path/x.yaml")

    def test_raises_on_non_yaml_extension(self, tmp_path):
        p1 = _write_yaml(str(tmp_path), "a.yaml", YAML_A)
        txt_path = os.path.join(str(tmp_path), "b.txt")
        with open(txt_path, "w") as f:
            f.write("element1:\n  name: Test\n")
        with pytest.raises(ValueError, match="Not a YAML"):
            load_yaml_files(p1, txt_path)

    def test_raises_on_empty_path_string(self, tmp_path):
        p1 = _write_yaml(str(tmp_path), "a.yaml", YAML_A)
        with pytest.raises(ValueError):
            load_yaml_files(p1, "  ")


# ===== Test 2: compare_kde_names ==========================================

class TestCompareKdeNames:
    def test_detects_name_differences(self, tmp_path):
        """Function must report names present in one file but not the other."""
        out_path = compare_kde_names(YAML_A, YAML_B, "a.yaml", "b.yaml", str(tmp_path))

        assert os.path.isfile(out_path)
        content = open(out_path).read()

        # "Network Policies" is in A but not B; "Pod Security" is in B but not A
        assert "Network Policies" in content
        assert "Pod Security" in content
        # "Audit Logging" and "RBAC" are in both — should NOT be flagged
        assert "Audit Logging" not in content
        assert "RBAC" not in content

    def test_no_differences_when_identical(self, tmp_path):
        """Function must write NO DIFFERENCES message when names are the same."""
        out_path = compare_kde_names(
            YAML_IDENTICAL, YAML_IDENTICAL, "same1.yaml", "same2.yaml", str(tmp_path)
        )
        content = open(out_path).read()
        assert "NO DIFFERENCES IN REGARDS TO ELEMENT NAMES" in content


# ===== Test 3: compare_kde_requirements ===================================

class TestCompareKdeRequirements:
    def test_detects_requirement_differences(self, tmp_path):
        """Function must output tuple lines for each differing requirement."""
        out_path = compare_kde_requirements(
            YAML_A, YAML_B, "a.yaml", "b.yaml", str(tmp_path)
        )

        assert os.path.isfile(out_path)
        lines = open(out_path).read().splitlines()

        # "Audit Logging" - req "2.1.2 Retain logs 90 days" is only in A
        audit_lines = [l for l in lines if l.startswith("Audit Logging")]
        assert any("2.1.2 Retain logs 90 days" in l for l in audit_lines)
        assert any("ABSENT-IN-b.yaml" in l for l in audit_lines)

        # "Network Policies" is entirely absent from B → NA entry
        net_lines = [l for l in lines if l.startswith("Network Policies")]
        assert len(net_lines) == 1
        assert net_lines[0].endswith(",NA")

        # "Pod Security" is entirely absent from A → NA entry
        pod_lines = [l for l in lines if l.startswith("Pod Security")]
        assert len(pod_lines) == 1
        assert pod_lines[0].endswith(",NA")

    def test_no_differences_when_identical(self, tmp_path):
        """Function must write NO DIFFERENCES message when both files are identical."""
        out_path = compare_kde_requirements(
            YAML_IDENTICAL, YAML_IDENTICAL, "same1.yaml", "same2.yaml", str(tmp_path)
        )
        content = open(out_path).read()
        assert "NO DIFFERENCES IN REGARDS TO ELEMENT REQUIREMENTS" in content

    def test_output_format_is_comma_separated(self, tmp_path):
        """Each difference line must follow the NAME,ABSENT-IN-X,PRESENT-IN-Y,REQ format."""
        out_path = compare_kde_requirements(
            YAML_A, YAML_B, "a.yaml", "b.yaml", str(tmp_path)
        )
        lines = [l for l in open(out_path).read().splitlines() if l and not l.startswith("#")]
        for line in lines:
            parts = line.split(",")
            assert len(parts) == 4, f"Expected 4 comma-separated fields, got: {line!r}"
            assert "ABSENT-IN-" in parts[1]
            assert "PRESENT-IN-" in parts[2]