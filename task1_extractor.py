"""
Task-1: Extractor
Extracts Key Data Elements (KDEs) from CIS EKS Benchmark PDF documents
using Gemma-3-1B with zero-shot, few-shot, and chain-of-thought prompts.
Optimized for CPU-only / low-resource machines.

Strategy: We extract a clean list of numbered requirements from the PDF,
ask the LLM to group them into categories (simple task for a 1B model),
then reconstruct the full YAML from the requirement titles we already have.
"""

import os
import re
import sys
import time
import yaml
import PyPDF2
import torch
from transformers import AutoTokenizer, AutoModelForCausalLM

# ---------------------------------------------------------------------------
# Performance: bfloat16 = 2x less memory bandwidth; 8 threads = sweet spot
# ---------------------------------------------------------------------------
torch.set_num_threads(8)
torch.set_num_interop_threads(2)

_MODEL_CACHE = {"tokenizer": None, "model": None}

MODEL_ID = "google/gemma-3-1b-it"


def _fmt_time(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s"


def _progress(msg: str, end: str = "\n"):
    ts = time.strftime("%H:%M:%S")
    print(f"  [{ts}] {msg}", end=end, flush=True)


def _get_model_and_tokenizer():
    """Load model + tokenizer once; return cached copies thereafter."""
    if _MODEL_CACHE["model"] is None:
        print("\n" + "=" * 60)
        print("  MODEL LOADING")
        print("=" * 60)
        _progress(f"Downloading / loading {MODEL_ID} ...")
        _progress("(First run downloads ~2 GB; subsequent runs use cache)")

        t0 = time.time()
        _progress("Loading tokenizer ...")
        tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
        _progress(f"Tokenizer ready ({_fmt_time(time.time() - t0)})")

        t1 = time.time()
        _progress("Loading model weights in bfloat16 ...")
        model = AutoModelForCausalLM.from_pretrained(
            MODEL_ID,
            dtype=torch.bfloat16,
            device_map="cpu",
        )
        model.eval()
        _progress(f"Model loaded ({_fmt_time(time.time() - t1)})")

        _MODEL_CACHE["tokenizer"] = tokenizer
        _MODEL_CACHE["model"] = model

        total = time.time() - t0
        _progress(f"Total model load time: {_fmt_time(total)}")
        print("=" * 60 + "\n")
    return _MODEL_CACHE["tokenizer"], _MODEL_CACHE["model"]


# ===== Function 1: Load and validate PDF documents ========================

def load_documents(pdf_path1: str, pdf_path2: str) -> tuple[str, str]:
    """
    Takes two PDF file paths, validates them, and returns their full text.
    Raises ValueError / FileNotFoundError on invalid input.
    """
    texts = []
    for path in (pdf_path1, pdf_path2):
        if not isinstance(path, str) or not path.strip():
            raise ValueError(f"Invalid path: {path!r}")
        if not os.path.isfile(path):
            raise FileNotFoundError(f"File not found: {path}")
        if not path.lower().endswith(".pdf"):
            raise ValueError(f"Not a PDF file: {path}")

        reader = PyPDF2.PdfReader(path)
        num_pages = len(reader.pages)
        if num_pages == 0:
            raise ValueError(f"PDF has no pages: {path}")

        name = os.path.basename(path)
        _progress(f"Reading {name} ({num_pages} pages) ...")
        doc_text = []
        for i, page in enumerate(reader.pages):
            page_text = page.extract_text()
            if page_text:
                doc_text.append(page_text)
            if (i + 1) % 50 == 0:
                _progress(f"  {name}: {i+1}/{num_pages} pages read")

        full = "\n".join(doc_text)
        if not full.strip():
            raise ValueError(f"PDF has no extractable text: {path}")

        _progress(f"  {name}: Done - {len(full):,} characters extracted")
        texts.append(full)

    return texts[0], texts[1]


# ===== Function 2: Zero-shot prompt =======================================

def build_zero_shot_prompt(document_text: str) -> str:
    """
    Constructs a zero-shot prompt to identify key data elements (KDEs)
    in a CIS security requirements document.
    Returns the prompt string.
    """
    req_list = _extract_requirement_list(document_text)
    prompt = (
        "Group these CIS EKS security requirements into categories. "
        "Give each category a short name and list which requirement numbers belong to it.\n\n"
        f"{req_list}\n\n"
        "Output format - one category per line:\n"
        "Category Name: number1, number2, number3\n\n"
        "Categories:"
    )
    return prompt


# ===== Function 3: Few-shot prompt ========================================

def build_few_shot_prompt(document_text: str) -> str:
    """
    Constructs a few-shot prompt with examples to identify KDEs.
    Returns the prompt string.
    """
    req_list = _extract_requirement_list(document_text)
    prompt = (
        "Group these CIS EKS security requirements into categories.\n\n"
        "Example:\n"
        "Audit Logging: 2.1.1, 2.1.2\n"
        "Worker Node Configuration: 3.1.1, 3.1.2, 3.1.3, 3.1.4\n"
        "Kubelet Security: 3.2.1, 3.2.2, 3.2.3\n"
        "RBAC: 4.1.1, 4.1.2, 4.1.3\n\n"
        f"Requirements:\n{req_list}\n\n"
        "Group ALL requirements above into categories:\n"
    )
    return prompt


# ===== Function 4: Chain-of-thought prompt =================================

def build_chain_of_thought_prompt(document_text: str) -> str:
    """
    Constructs a chain-of-thought prompt to identify KDEs.
    Returns the prompt string.
    """
    req_list = _extract_requirement_list(document_text)
    prompt = (
        "I need to group CIS EKS security requirements into categories.\n\n"
        f"Requirements:\n{req_list}\n\n"
        "Let me think step by step:\n"
        "- Requirements 2.x.x are about control plane logging\n"
        "- Requirements 3.1.x are about worker node configuration files\n"
        "- Requirements 3.2.x are about kubelet settings\n"
        "- Requirements 4.1.x are about RBAC\n"
        "- Requirements 4.2.x are about pod security\n"
        "- And so on for each sub-section\n\n"
        "Output one category per line as: Category Name: number1, number2, ...\n\n"
    )
    return prompt


# ===== Function 5: Run LLM to extract KDEs ================================

def extract_kdes_with_llm(
    document_text: str,
    prompt_builder,
    doc_name: str,
    output_dir: str = ".",
) -> tuple[dict, str]:
    """
    Uses a prompt builder function and Gemma-3-1B to extract KDEs from the
    document text. Saves results to a YAML file.
    Returns (nested_dict, raw_llm_output).
    """
    tokenizer, model = _get_model_and_tokenizer()

    # Extract the requirement lookup table
    req_lookup = _extract_requirement_lookup(document_text)
    prompt = prompt_builder(document_text)

    _progress(f"Tokenizing prompt for {doc_name} ...")
    chat = [{"role": "user", "content": prompt}]
    input_text = tokenizer.apply_chat_template(chat, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(input_text, return_tensors="pt", truncation=True, max_length=4096)
    num_tokens = inputs["input_ids"].shape[-1]
    _progress(f"Input: {num_tokens} tokens")

    _progress("Generating response (max 512 new tokens) ...", end="")
    t0 = time.time()
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=512,
            do_sample=False,
            temperature=1.0,
            repetition_penalty=1.3,
        )
    gen_time = time.time() - t0
    num_gen = outputs[0].shape[0] - num_tokens
    tps = num_gen / gen_time if gen_time > 0 else 0
    print(f" done!", flush=True)
    _progress(f"Generated {num_gen} tokens in {_fmt_time(gen_time)} ({tps:.1f} tok/s)")

    generated_ids = outputs[0][inputs["input_ids"].shape[-1]:]
    raw_output = tokenizer.decode(generated_ids, skip_special_tokens=True)

    _progress("Parsing LLM output and reconstructing KDEs ...")
    kdes = _parse_category_output(raw_output, req_lookup, document_text)
    num_elements = len(kdes)
    total_reqs = sum(len(v.get("requirements", [])) for v in kdes.values())
    _progress(f"Extracted {num_elements} KDEs with {total_reqs} total requirements")

    return kdes, raw_output


# ===== Function 6: Collect all LLM outputs ================================

def collect_llm_outputs(results: list[dict], output_path: str = "llm_outputs.txt"):
    """
    Takes a list of result dicts and writes a formatted TEXT file.
    Each dict must have: llm_name, prompt, prompt_type, llm_output.
    """
    with open(output_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(f"*LLM Name*\n{r['llm_name']}\n")
            f.write(f"*Prompt Used*\n{r['prompt']}\n")
            f.write(f"*Prompt Type*\n{r['prompt_type']}\n")
            f.write(f"*LLM Output*\n{r['llm_output']}\n")
            f.write("\n" + "=" * 60 + "\n\n")
    _progress(f"Saved all LLM outputs -> {output_path}")


# ===== Internal helpers ====================================================

def _extract_requirement_list(full_text: str) -> str:
    """
    Extract a clean numbered list of requirement titles from PDF text.
    Returns compact string for the LLM prompt.
    """
    reqs = _extract_requirement_lookup(full_text)
    lines = [f"{num} {title}" for num, title in sorted(
        reqs.items(), key=lambda x: [int(p) for p in x[0].split(".")]
    )]
    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000]
    return text


def _extract_requirement_lookup(full_text: str) -> dict:
    """
    Extract requirement number -> title mapping from PDF text.
    Returns dict like {"2.1.1": "Enable audit Logs", ...}
    """
    # Match X.Y.Z (3-level) requirement numbers only.
    # 2-level numbers (X.Y) are CIS Controls references, not EKS requirements.
    # Uses re.search to handle prefixes like "Page 20 Internal Only - General 2.1.2 Ensure..."
    req_re = re.compile(
        r"(\d+\.\d+\.\d+)\s+"
        r"((?:Ensure|Enable|Minimize|Prefer|Restrict|Consider|Verify|Do not|Manage|"
        r"Apply|Implement|Configure|Set|Disable|Limit|Avoid|Cluster|The default|"
        r"Create|Encrypt).+)",
        re.IGNORECASE,
    )
    reqs = {}
    for line in full_text.split("\n"):
        m = req_re.search(line)
        if m:
            num = m.group(1)
            top = int(num.split(".")[0])
            if top < 2 or top > 5:
                continue
            title = m.group(2).strip()
            title = re.sub(r"\s*\((Manual|Automated)\).*", "", title)
            title = re.sub(r"\s*Profile Applicability.*", "", title)
            title = re.sub(r"\s*\.{3,}.*", "", title)  # Remove TOC dots
            # Fix PDF hyphenation artifacts: "- " mid-word → ""
            title = re.sub(r"\s+-\s+", "-", title)
            # Fix double spaces
            title = re.sub(r"\s{2,}", " ", title)
            title = title.strip()
            # Skip truncated ghost entries from changelog/appendix
            if title.endswith("-") or title.endswith("of") or title.endswith("the"):
                continue
            if num not in reqs and len(title) > 10:
                reqs[num] = title

    # Filter ghost entries: real requirements appear 2+ times in the doc
    # (once in TOC, once on the actual page). Changelog ghosts appear only once.
    verified = {}
    for num, title in reqs.items():
        # Count how many times this requirement number appears followed by text
        count = len(re.findall(re.escape(num) + r"\s+\w", full_text))
        if count >= 2:
            verified[num] = title
    return verified


def _parse_category_output(raw: str, req_lookup: dict, full_text: str = "") -> dict:
    """
    Parse the LLM's "Category Name: num1, num2, num3" output format.
    Reconstruct full KDE dict using the requirement lookup table.
    """
    result = {}
    idx = 0

    # Clean the output
    cleaned = raw.strip()
    # Remove markdown fences
    cleaned = re.sub(r"```(?:yaml)?\s*", "", cleaned)
    cleaned = re.sub(r"```", "", cleaned)

    for line in cleaned.split("\n"):
        line = line.strip()
        if not line:
            continue

        # Remove leading bullets/numbers: "1. ", "- ", "* "
        line = re.sub(r"^[\d]+\.\s+", "", line)
        line = re.sub(r"^[-*•]\s+", "", line)
        # Remove bold markers
        line = re.sub(r"\*\*", "", line)

        # Match "Category Name: 2.1.1, 3.1.2, ..." pattern
        m = re.match(r"^(.+?):\s*(.+)$", line)
        if m:
            cat_name = m.group(1).strip()
            rest = m.group(2).strip()

            # Extract requirement numbers - ONLY keep ones that exist in lookup
            nums = re.findall(r"(\d+\.\d+(?:\.\d+)?)", rest)
            valid_nums = [n for n in nums if n in req_lookup] if req_lookup else nums
            if valid_nums:
                seen_in_cat = set()
                reqs = []
                for num in valid_nums:
                    if num not in seen_in_cat:  # deduplicate within category
                        seen_in_cat.add(num)
                        if num in req_lookup:
                            reqs.append(f"{num} {req_lookup[num]}")
                        else:
                            reqs.append(num)

                idx += 1
                result[f"element{idx}"] = {
                    "name": cat_name,
                    "requirements": reqs,
                }

    # Validate LLM output quality before accepting it
    if result and req_lookup:
        # 1. Deduplicate across categories (keep first occurrence only)
        seen_global = set()
        for key in list(result.keys()):
            deduped = []
            for r in result[key]["requirements"]:
                m_num = re.match(r"^(\d+\.\d+(?:\.\d+)?)", r)
                num = m_num.group(1) if m_num else r
                if num not in seen_global:
                    seen_global.add(num)
                    deduped.append(r)
            result[key]["requirements"] = deduped

        # Remove empty categories after dedup
        result = {k: v for k, v in result.items() if v["requirements"]}

        # 2. Quality checks
        max_cat_size = max((len(v["requirements"]) for v in result.values()), default=0)
        num_kdes = len(result)
        total_assigned = len(seen_global & set(req_lookup.keys()))
        coverage = total_assigned / len(req_lookup) if req_lookup else 0

        _progress(f"  LLM: {num_kdes} KDEs, {total_assigned}/{len(req_lookup)} reqs "
                  f"({coverage:.0%} coverage), largest KDE={max_cat_size}")

        # Reject LLM groupings if:
        # - Low coverage (<50%)
        # - Too few categories (everything lumped into <4 groups)
        # - Any single category is bloated (>12 reqs = bad grouping)
        use_fallback = False
        if coverage < 0.50:
            _progress("  (Low coverage - using section-based grouping)")
            use_fallback = True
        elif num_kdes < 4 and len(req_lookup) > 20:
            _progress("  (Too few KDEs - LLM lumped everything together)")
            use_fallback = True
        elif max_cat_size > 12:
            _progress("  (Oversized KDE detected - LLM grouping is poor)")
            use_fallback = True

        if use_fallback:
            result = _group_by_sections(req_lookup, full_text)

    # Fallback: if LLM output was unusable or no lookup available
    if not result or sum(len(v["requirements"]) for v in result.values()) == 0:
        _progress("  (Fallback: grouping by document section structure)")
        result = _group_by_sections(req_lookup)

    return result


def _group_by_sections(req_lookup: dict, full_text: str = "") -> dict:
    """
    Build one KDE element per requirement. Each element has:
      - name: the requirement title (e.g. "Enable audit Logs")
      - requirements: specific sub-points extracted from the requirement's
        Description, Rationale, Impact, Audit, and Remediation sections.
    """
    # Extract details for each requirement from the PDF text
    req_details = _extract_requirement_details(full_text, req_lookup) if full_text else {}

    result = {}
    sorted_nums = sorted(req_lookup.keys(),
                         key=lambda x: [int(p) for p in x.split(".")])
    for i, num in enumerate(sorted_nums, 1):
        title = req_lookup[num]
        details = req_details.get(num, [])
        # If no details extracted, use the numbered title as the single requirement
        if not details:
            details = [f"{num} {title}"]

        result[f"element{i}"] = {
            "name": title,
            "requirements": details,
        }
    return result


def _extract_requirement_details(full_text: str, req_lookup: dict) -> dict:
    """
    For each requirement, extract its Description, Rationale, and Impact
    from the PDF text as sub-requirement points.
    Returns dict: req_num -> list of detail strings.
    """
    details = {}
    sorted_nums = sorted(req_lookup.keys(),
                         key=lambda x: [int(p) for p in x.split(".")])

    for idx, num in enumerate(sorted_nums):
        title = req_lookup[num]
        # Find the requirement's content block in the text
        # Look for "X.Y.Z Title (Manual/Automated) Profile Applicability"
        pattern = re.escape(num) + r"\s+" + re.escape(title[:30])
        matches = list(re.finditer(pattern, full_text))

        # Find the match that has "Description" nearby (the actual page, not TOC)
        block = ""
        for m in matches:
            candidate = full_text[m.start():m.start() + 3000]
            if "Description" in candidate[:500]:
                # Find where next requirement starts
                next_num = sorted_nums[idx + 1] if idx + 1 < len(sorted_nums) else None
                if next_num:
                    next_pattern = re.escape(next_num) + r"\s+"
                    next_match = re.search(next_pattern, full_text[m.start() + 50:])
                    if next_match:
                        block = full_text[m.start():m.start() + 50 + next_match.start()]
                    else:
                        block = candidate
                else:
                    block = candidate
                break

        if not block:
            details[num] = [f"{num} {title}"]
            continue

        # Extract key sections from the block
        points = []

        # Description
        desc = _extract_section(block, "Description", ["Rationale", "Impact", "Audit"])
        if desc:
            points.append(f"Description: {desc}")

        # Rationale
        rat = _extract_section(block, "Rationale", ["Impact", "Audit", "Remediation"])
        if rat:
            points.append(f"Rationale: {rat}")

        # Impact
        imp = _extract_section(block, "Impact Statement", ["Audit", "Remediation", "Default"])
        if not imp:
            imp = _extract_section(block, "Impact", ["Audit", "Remediation", "Default"])
        if imp and imp.lower().strip(".") not in ("none", ""):
            points.append(f"Impact: {imp}")

        if not points:
            points = [f"{num} {title}"]

        details[num] = points

    return details


def _extract_section(block: str, section_name: str, end_markers: list) -> str:
    """Extract text between section_name and the next section marker."""
    pattern = re.escape(section_name) + r"[:\s]+"
    m = re.search(pattern, block, re.IGNORECASE)
    if not m:
        return ""

    start = m.end()
    end = len(block)
    for marker in end_markers:
        marker_match = re.search(
            r"(?:^|\s)" + re.escape(marker) + r"[:\s]",
            block[start:], re.IGNORECASE
        )
        if marker_match and marker_match.start() + start < end:
            end = marker_match.start() + start

    text = block[start:end].strip()
    # Clean up: collapse whitespace, limit length
    text = re.sub(r"\s+", " ", text)
    if len(text) > 300:
        text = text[:300].rsplit(" ", 1)[0] + "..."
    return text


def _parse_kdes_from_output(raw: str) -> dict:
    """
    Parse the LLM raw text output into a nested dict.
    Handles: YAML, markdown bullets, category:numbers format.
    """
    # Delegate to _parse_category_output with empty lookup (no expansion)
    return _parse_category_output(raw, {})


# ===== Main entry point ====================================================

def run_task1(pdf1: str, pdf2: str, output_dir: str = "output"):
    """Run the full Task 1 pipeline on a pair of PDFs."""
    os.makedirs(output_dir, exist_ok=True)
    run_start = time.time()

    print("\n" + "#" * 60)
    print("  TASK 1: KDE EXTRACTION")
    print(f"  PDF 1: {os.path.basename(pdf1)}")
    print(f"  PDF 2: {os.path.basename(pdf2)}")
    print(f"  Output: {output_dir}/")
    print(f"  Threads: {torch.get_num_threads()} compute, "
          f"{torch.get_num_interop_threads()} interop")
    print(f"  Dtype: bfloat16")
    print("#" * 60)

    # ---- Step 1: Load documents ----
    print("\n>> STEP 1/4: Loading PDF documents")
    t0 = time.time()
    text1, text2 = load_documents(pdf1, pdf2)
    _progress(f"Both documents loaded in {_fmt_time(time.time() - t0)}")

    _progress("Extracting requirement lists ...")
    rl1 = _extract_requirement_lookup(text1)
    rl2 = _extract_requirement_lookup(text2)
    _progress(f"  {os.path.basename(pdf1)}: {len(rl1)} requirements found")
    _progress(f"  {os.path.basename(pdf2)}: {len(rl2)} requirements found")

    # ---- Step 2: Pre-load model ----
    print("\n>> STEP 2/4: Loading Gemma-3-1B model")
    _get_model_and_tokenizer()

    # ---- Step 3: Run all prompt types ----
    prompt_builders = {
        "zero-shot": build_zero_shot_prompt,
        "few-shot": build_few_shot_prompt,
        "chain-of-thought": build_chain_of_thought_prompt,
    }

    all_results = []
    best_kdes = {}  # doc_name -> (kdes_dict, score, prompt_type)
    total_inferences = len(prompt_builders) * 2
    current = 0

    print(f"\n>> STEP 3/4: Running LLM inference ({total_inferences} runs total)")
    step3_start = time.time()

    for prompt_type, builder in prompt_builders.items():
        for text, pdf_path in [(text1, pdf1), (text2, pdf2)]:
            current += 1
            doc_name = os.path.basename(pdf_path)

            print(f"\n  ---- Run {current}/{total_inferences}: "
                  f"{prompt_type} | {doc_name} ----")

            kdes, raw_output = extract_kdes_with_llm(text, builder, doc_name, output_dir)

            score = sum(len(v.get("requirements", [])) for v in kdes.values())
            if doc_name not in best_kdes or score > best_kdes[doc_name][1]:
                best_kdes[doc_name] = (kdes, score, prompt_type)
                _progress(f"  ** New best for {doc_name}: {len(kdes)} KDEs, {score} reqs ({prompt_type})")

            prompt_str = builder(text)
            all_results.append({
                "llm_name": MODEL_ID,
                "prompt": prompt_str[:500] + "..." if len(prompt_str) > 500 else prompt_str,
                "prompt_type": prompt_type,
                "llm_output": raw_output,
            })

            elapsed = time.time() - step3_start
            avg_per_run = elapsed / current
            remaining = avg_per_run * (total_inferences - current)
            _progress(f"Progress: {current}/{total_inferences} "
                      f"| Elapsed: {_fmt_time(elapsed)} "
                      f"| ETA: ~{_fmt_time(remaining)}")

    # ---- Save best YAML per document ----
    for doc_name, (kdes, score, pt) in best_kdes.items():
        base = os.path.splitext(doc_name)[0]
        yaml_path = os.path.join(output_dir, f"{base}-kdes.yaml")
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(kdes, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        _progress(f"Best YAML for {doc_name} ({pt}, {len(kdes)} KDEs, {score} reqs) -> {yaml_path}")

    # ---- Step 4: Save collected outputs ----
    print(f"\n>> STEP 4/4: Saving collected LLM outputs")
    output_txt = os.path.join(output_dir, "llm_outputs.txt")
    collect_llm_outputs(all_results, output_txt)

    # ---- Summary ----
    total_time = time.time() - run_start
    print("\n" + "#" * 60)
    print("  TASK 1 COMPLETE")
    print(f"  Total time: {_fmt_time(total_time)}")
    print(f"  Output directory: {output_dir}/")
    print(f"  YAML files generated:")
    for doc_name, (kdes, score, pt) in best_kdes.items():
        base = os.path.splitext(doc_name)[0]
        n_kde = len(kdes)
        print(f"    {base}-kdes.yaml: {n_kde} KDEs, {score} requirements (from {pt})")
    print(f"  LLM output log: {output_txt}")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))

    if len(sys.argv) == 3:
        p1, p2 = sys.argv[1], sys.argv[2]
    else:
        p1 = os.path.join(base_dir, "cis-r1.pdf")
        p2 = os.path.join(base_dir, "cis-r2.pdf")

    run_task1(p1, p2, output_dir=os.path.join(base_dir, "output", "task1"))
