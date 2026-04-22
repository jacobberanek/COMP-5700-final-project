"""
Task-2: Comparator
Compares two KDE YAML files produced by Task-1 and identifies differences
in (1) element names and (2) element names + requirements.
"""

import os
import yaml


# ===== Function 1: Load and validate YAML files ===========================

def load_yaml_files(yaml_path1: str, yaml_path2: str) -> tuple[dict, dict]:
    """
    Takes two YAML file paths produced by Task-1, validates them,
    and returns their contents as dicts.
    Raises ValueError / FileNotFoundError on invalid input.
    """
    results = []
    for path in (yaml_path1, yaml_path2):
        if not isinstance(path, str) or not path.strip():
            raise ValueError(f"Invalid path: {path!r}")
        if not os.path.isfile(path):
            raise FileNotFoundError(f"File not found: {path}")
        if not path.lower().endswith((".yaml", ".yml")):
            raise ValueError(f"Not a YAML file: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not isinstance(data, dict):
            raise ValueError(f"YAML file does not contain a mapping: {path}")
        if not data:
            raise ValueError(f"YAML file is empty: {path}")

        results.append(data)

    return results[0], results[1]


# ===== Function 2: Compare KDE names only =================================

def compare_kde_names(
    data1: dict,
    data2: dict,
    file1_name: str,
    file2_name: str,
    output_dir: str = ".",
) -> str:
    """
    Identifies differences in KDE *names* between two YAML dicts.
    Writes a TEXT file and returns its path.
    """
    names1 = {_normalize_req(v["name"]) for v in data1.values() if "name" in v}
    names2 = {_normalize_req(v["name"]) for v in data2.values() if "name" in v}

    only_in_1 = sorted(names1 - names2)
    only_in_2 = sorted(names2 - names1)

    base1 = os.path.basename(file1_name)
    base2 = os.path.basename(file2_name)

    out_name = f"name-diff_{_stem(base1)}_vs_{_stem(base2)}.txt"
    out_path = os.path.join(output_dir, out_name)

    os.makedirs(output_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        if not only_in_1 and not only_in_2:
            f.write("NO DIFFERENCES IN REGARDS TO ELEMENT NAMES\n")
        else:
            if only_in_1:
                f.write(f"# KDE names present in {base1} but absent in {base2}:\n")
                for name in only_in_1:
                    f.write(f"  {name}\n")
                f.write("\n")
            if only_in_2:
                f.write(f"# KDE names present in {base2} but absent in {base1}:\n")
                for name in only_in_2:
                    f.write(f"  {name}\n")

    print(f"  [compare_kde_names] Written -> {out_path}")
    return out_path


# ===== Function 3: Compare KDE names + requirements =======================

def compare_kde_requirements(
    data1: dict,
    data2: dict,
    file1_name: str,
    file2_name: str,
    output_dir: str = ".",
) -> str:
    """
    Identifies differences in KDE names AND requirements between two YAML dicts.
    Writes a TEXT file in the tuple format specified in README and returns its path.

    Output format:
      NAME,ABSENT-IN-<FILE>,PRESENT-IN-<FILE>,NA          # KDE in one file only
      NAME,ABSENT-IN-<FILE>,PRESENT-IN-<FILE>,REQ          # req present in one file only
    """
    base1 = os.path.basename(file1_name)
    base2 = os.path.basename(file2_name)

    # Build name -> requirements mappings (normalize to neutralize PDF artifacts)
    name_to_reqs1 = {_normalize_req(v["name"]): {_normalize_req(r) for r in v.get("requirements", [])} for v in data1.values() if "name" in v}
    name_to_reqs2 = {_normalize_req(v["name"]): {_normalize_req(r) for r in v.get("requirements", [])} for v in data2.values() if "name" in v}

    all_names = sorted(name_to_reqs1.keys() | name_to_reqs2.keys())

    lines = []

    for name in all_names:
        in1 = name in name_to_reqs1
        in2 = name in name_to_reqs2

        if in1 and not in2:
            # KDE entirely absent from file 2
            lines.append(f"{name},ABSENT-IN-{base2},PRESENT-IN-{base1},NA")

        elif in2 and not in1:
            # KDE entirely absent from file 1
            lines.append(f"{name},ABSENT-IN-{base1},PRESENT-IN-{base2},NA")

        else:
            # KDE present in both — compare requirements
            reqs1 = name_to_reqs1[name]
            reqs2 = name_to_reqs2[name]

            only_in_1 = sorted(reqs1 - reqs2)
            only_in_2 = sorted(reqs2 - reqs1)

            for req in only_in_1:
                lines.append(f"{name},ABSENT-IN-{base2},PRESENT-IN-{base1},{req}")
            for req in only_in_2:
                lines.append(f"{name},ABSENT-IN-{base1},PRESENT-IN-{base2},{req}")

    out_name = f"req-diff_{_stem(base1)}_vs_{_stem(base2)}.txt"
    out_path = os.path.join(output_dir, out_name)

    os.makedirs(output_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        if not lines:
            f.write("NO DIFFERENCES IN REGARDS TO ELEMENT REQUIREMENTS\n")
        else:
            for line in lines:
                f.write(line + "\n")

    print(f"  [compare_kde_requirements] Written -> {out_path}")
    return out_path


# ===== Internal helpers ===================================================

def _stem(filename: str) -> str:
    """Return filename without extension."""
    return os.path.splitext(filename)[0]


def _normalize_req(req: str) -> str:
    """
    Normalize a requirement string to neutralize PDF extraction artifacts
    so that semantically identical requirements compare as equal.
    Handles: 'read -only' -> 'read-only', double spaces, trailing whitespace,
    and space before punctuation like 'root:root .' -> 'root:root.'
    """
    import re
    # Fix spaced hyphens: 'read -only' or 'read- only' -> 'read-only'
    req = re.sub(r'\s+-\s*', '-', req)
    req = re.sub(r'\s*-\s+', '-', req)
    # Fix space before punctuation: 'root:root .' -> 'root:root.'
    req = re.sub(r'\s+([.,;:!?])', r'\1', req)
    # Collapse multiple spaces
    req = re.sub(r' {2,}', ' ', req)
    return req.strip()


# ===== Main entry point ===================================================

def run_task2(yaml1: str, yaml2: str, output_dir: str = "output"):
    """Run the full Task-2 pipeline on a pair of YAML files from Task-1."""
    os.makedirs(output_dir, exist_ok=True)

    print("\n" + "#" * 60)
    print("  TASK 2: KDE COMPARISON")
    print(f"  YAML 1: {os.path.basename(yaml1)}")
    print(f"  YAML 2: {os.path.basename(yaml2)}")
    print(f"  Output: {output_dir}/")
    print("#" * 60)

    print("\n>> STEP 1/3: Loading YAML files")
    data1, data2 = load_yaml_files(yaml1, yaml2)
    print(f"  {os.path.basename(yaml1)}: {len(data1)} KDEs loaded")
    print(f"  {os.path.basename(yaml2)}: {len(data2)} KDEs loaded")

    print("\n>> STEP 2/3: Comparing KDE names")
    name_diff_path = compare_kde_names(data1, data2, yaml1, yaml2, output_dir)

    print("\n>> STEP 3/3: Comparing KDE names + requirements")
    req_diff_path = compare_kde_requirements(data1, data2, yaml1, yaml2, output_dir)

    print("\n" + "#" * 60)
    print("  TASK 2 COMPLETE")
    print(f"  Name diff file:       {name_diff_path}")
    print(f"  Requirement diff file:{req_diff_path}")
    print("#" * 60 + "\n")

    return name_diff_path, req_diff_path


if __name__ == "__main__":
    import sys

    base_dir = os.path.dirname(os.path.abspath(__file__))
    task1_dir = os.path.join(base_dir, "output", "task1")
    task2_dir = os.path.join(base_dir, "output", "task2")

    if len(sys.argv) == 3:
        y1, y2 = sys.argv[1], sys.argv[2]
    else:
        # Default: compare first two PDFs' YAML outputs from task1 directory
        y1 = os.path.join(task1_dir, "cis-r1-kdes.yaml")
        y2 = os.path.join(task1_dir, "cis-r2-kdes.yaml")

    run_task2(y1, y2, output_dir=task2_dir)