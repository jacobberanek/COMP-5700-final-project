# PROMPT.md

This file documents all prompts used in Task-1 to identify Key Data Elements (KDEs)
from CIS EKS Benchmark security requirements documents using `google/gemma-3-1b-it`.

In all three prompts, `{requirements}` represents the numbered list of requirement
titles extracted from the input PDF (e.g. `2.1.1 Ensure audit logs are configured`).
This list is generated dynamically by `_extract_requirement_list()` in `task1_extractor.py`
and inserted into the prompt at runtime.

---

## zero-shot

No examples are provided. The model is asked to group requirements into categories
based only on the task description and the requirement list.

```
Group these CIS EKS security requirements into categories. Give each category a short name and list which requirement numbers belong to it.

{requirements}

Output format - one category per line:
Category Name: number1, number2, number3

Categories:
```

---

## few-shot

Four labelled examples are provided before the actual requirement list so the model
can learn the expected output format and grouping style from the examples.

```
Group these CIS EKS security requirements into categories.

Example:
Audit Logging: 2.1.1, 2.1.2
Worker Node Configuration: 3.1.1, 3.1.2, 3.1.3, 3.1.4
Kubelet Security: 3.2.1, 3.2.2, 3.2.3
RBAC: 4.1.1, 4.1.2, 4.1.3

Requirements:
{requirements}

Group ALL requirements above into categories:
```

---

## chain-of-thought

The prompt primes the model with explicit step-by-step reasoning about how CIS EKS
requirement numbers map to security domains before asking it to produce the groupings.

```
I need to group CIS EKS security requirements into categories.

Requirements:
{requirements}

Let me think step by step:
- Requirements 2.x.x are about control plane logging
- Requirements 3.1.x are about worker node configuration files
- Requirements 3.2.x are about kubelet settings
- Requirements 4.1.x are about RBAC
- Requirements 4.2.x are about pod security
- And so on for each sub-section

Output one category per line as: Category Name: number1, number2, ...
```