"""
Test cases for Task-1: Extractor
One test per function as specified in the README.
Run with: python -m pytest test_task1.py -v
"""

import os
import pytest
from unittest.mock import patch, MagicMock

from task1_extractor import (
    load_documents,
    build_zero_shot_prompt,
    build_few_shot_prompt,
    build_chain_of_thought_prompt,
    extract_kdes_with_llm,
    collect_llm_outputs,
)

# Minimal synthetic PDF text resembling a CIS EKS benchmark page.
# Each requirement number appears twice (TOC + page) to pass the
# "verified" filter in _extract_requirement_lookup.
SAMPLE_TEXT = """
Table of Contents
2.1.1 Ensure audit logs are enabled ............... 10
3.1.1 Ensure worker node config files are set ....... 20
4.1.1 Restrict cluster-admin role usage ............. 30

2.1.1 Ensure audit logs are enabled (Automated)
Description: Enable audit logging.

3.1.1 Ensure worker node config files are set (Manual)
Description: Worker node files should be owned by root.

4.1.1 Restrict cluster-admin role usage (Automated)
Description: Limit cluster-admin bindings.
"""


def _make_pdf(tmp_path, filename):
    """Write a minimal valid PDF and return its path."""
    from PyPDF2 import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    path = os.path.join(tmp_path, filename)
    with open(path, "wb") as f:
        writer.write(f)
    return path


# ===== Test 1: load_documents =============================================

def test_load_documents(tmp_path):
    """load_documents must return two non-empty strings from valid PDFs."""
    p1 = _make_pdf(str(tmp_path), "a.pdf")
    p2 = _make_pdf(str(tmp_path), "b.pdf")

    mock_page = MagicMock()
    mock_page.extract_text.return_value = SAMPLE_TEXT
    mock_reader = MagicMock()
    mock_reader.pages = [mock_page]

    with patch("task1_extractor.PyPDF2.PdfReader", return_value=mock_reader):
        text1, text2 = load_documents(p1, p2)

    assert isinstance(text1, str) and len(text1) > 0
    assert isinstance(text2, str) and len(text2) > 0


# ===== Test 2: build_zero_shot_prompt =====================================

def test_build_zero_shot_prompt():
    """build_zero_shot_prompt must return a string containing requirement numbers."""
    prompt = build_zero_shot_prompt(SAMPLE_TEXT)
    assert isinstance(prompt, str) and len(prompt) > 0
    assert any(num in prompt for num in ["2.1.1", "3.1.1", "4.1.1"])


# ===== Test 3: build_few_shot_prompt ======================================

def test_build_few_shot_prompt():
    """build_few_shot_prompt must include labelled examples."""
    prompt = build_few_shot_prompt(SAMPLE_TEXT)
    assert isinstance(prompt, str)
    assert "Example" in prompt or "Audit Logging" in prompt


# ===== Test 4: build_chain_of_thought_prompt ==============================

def test_build_chain_of_thought_prompt():
    """build_chain_of_thought_prompt must include step-by-step reasoning language."""
    prompt = build_chain_of_thought_prompt(SAMPLE_TEXT)
    assert isinstance(prompt, str)
    assert "step" in prompt.lower()


# ===== Test 5: extract_kdes_with_llm (LLM mocked) =========================

def test_extract_kdes_with_llm(tmp_path):
    """extract_kdes_with_llm must return a (dict, str) with valid KDE structure."""
    mock_tokenizer = MagicMock()
    mock_tokenizer.apply_chat_template.return_value = "chat"
    input_ids = MagicMock()
    input_ids.shape = [1, 10]
    mock_tokenizer.return_value = {"input_ids": input_ids}
    mock_tokenizer.decode.return_value = "Audit Logging: 2.1.1\nRBAC: 4.1.1\n"

    output_tensor = MagicMock()
    output_tensor.shape = [1, 15]
    output_tensor.__getitem__ = lambda self, idx: MagicMock(shape=[1, 15])
    mock_model = MagicMock()
    mock_model.generate.return_value = [output_tensor]

    with patch("task1_extractor._get_model_and_tokenizer",
               return_value=(mock_tokenizer, mock_model)):
        result, raw = extract_kdes_with_llm(
            SAMPLE_TEXT, build_zero_shot_prompt, "test-doc", str(tmp_path)
        )

    assert isinstance(result, dict)
    assert isinstance(raw, str)
    for val in result.values():
        assert "name" in val and "requirements" in val


# ===== Test 6: collect_llm_outputs ========================================

def test_collect_llm_outputs(tmp_path):
    """collect_llm_outputs must write a file containing all four section headers."""
    results = [{
        "llm_name": "google/gemma-3-1b-it",
        "prompt": "Group these requirements...",
        "prompt_type": "zero-shot",
        "llm_output": "Audit Logging: 2.1.1\n",
    }]
    out_path = os.path.join(str(tmp_path), "llm_outputs.txt")
    collect_llm_outputs(results, out_path)

    content = open(out_path).read()
    assert "*LLM Name*" in content
    assert "*Prompt Used*" in content
    assert "*Prompt Type*" in content
    assert "*LLM Output*" in content