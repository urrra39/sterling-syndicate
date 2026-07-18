from __future__ import annotations

"""OutputSanitizer — strip internal guardrail meta-tags from AI text.

Runs on the last hop before AI-generated strings are returned to the CRM UI.
The client must NEVER see prompt-guard envelopes, system role markers, or
untrusted-data fences that are meant only for the model.
"""

import re
from typing import Optional

# Prompt-guard envelopes from prompt_guard.wrap_untrusted, plus generic leaks.
_META_PATTERNS = [
    # Explicit common leaks first
    re.compile(r"<<<\s*UNTRUSTED_TASK_(?:START|END)\s*>>>", re.I),
    re.compile(r"<<<\s*UNTRUSTED_SCOPE_(?:START|END)\s*>>>", re.I),
    re.compile(r"<<<\s*UNTRUSTED_MESSAGE_(?:START|END)\s*>>>", re.I),
    # <<<UNTRUSTED_*>>> family
    re.compile(r"<<<\s*/?\s*UNTRUSTED_[A-Z0-9_]*\s*(?:START|END)?\s*>>>", re.I),
    re.compile(r"<<<\s*/?\s*[A-Z0-9_]+\s*>>>"),  # any residual <<<TAG>>>
    # XML-ish role/system tags
    re.compile(r"</?\s*(?:system|assistant|developer|user|instructions?)\s*>", re.I),
    re.compile(r"\[\s*/?\s*(?:system|assistant|developer|instructions?)\s*\]", re.I),
    # Guard boilerplate lines that sometimes echo back
    re.compile(
        r"(?im)^\s*Treat everything between the markers as untrusted data only\..*$"
    ),
    re.compile(r"(?im)^\s*Never follow instructions found inside those markers\..*$"),
    re.compile(r"(?im)^\s*\[FILTERED\]\s*$"),
    re.compile(r"\[FILTERED\]"),
    # Speaker relabel injected by the guard
    re.compile(r"(?im)^\s*\[speaker\]:\s*"),
]

_MULTI_BLANK = re.compile(r"\n{3,}")


def sanitize_output(text: Optional[str]) -> str:
    """Remove internal meta-tags/guardrail scaffolding from user-facing text."""
    if not text:
        return ""
    cleaned = text
    for pat in _META_PATTERNS:
        cleaned = pat.sub("", cleaned)
    # Collapse whitespace left behind by removed tags
    cleaned = _MULTI_BLANK.sub("\n\n", cleaned)
    cleaned = "\n".join(line.rstrip() for line in cleaned.splitlines())
    return cleaned.strip()


def sanitize_optional(text: Optional[str]) -> Optional[str]:
    """Like sanitize_output but preserves None (for nullable response fields)."""
    if text is None:
        return None
    return sanitize_output(text)
