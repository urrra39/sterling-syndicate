from __future__ import annotations

"""Compliance firewall — drop prohibited jobs before Scout/Writer spend tokens.

Fast keyword pass first (no API). Optional LLM only when ambiguous.
"""

import re
from dataclasses import dataclass
from typing import List, Tuple

# High-confidence ToS / platform-ban patterns (academic fraud, malware, hacking-for-hire)
_PROHIBITED: List[Tuple[str, re.Pattern[str]]] = [
    ("academic_fraud", re.compile(
        r"\b(?:write\s+(?:my|your|an?)\s+(?:essay|thesis|dissertation|term\s*paper)|"
        r"ghostwrit(?:e|ing)\s+(?:essay|paper|thesis)|"
        r"take\s+(?:my|your|an?)\s+(?:exam|test|quiz)|"
        r"complete\s+(?:my|your)\s+(?:homework|coursework|assignment)s?\s+for\s+me)\b",
        re.I,
    )),
    ("malware", re.compile(
        r"\b(?:ransomware|keylogger|botnet|trojan\s+horse|cryptominer|"
        r"steal(?:ing)?\s+(?:password|credential|cookie)s?|"
        r"build\s+(?:a\s+)?(?:virus|malware|spyware|rootkit))\b",
        re.I,
    )),
    ("hacking_hire", re.compile(
        r"\b(?:hack(?:ing)?\s+(?:into|someone|instagram|facebook|gmail|whatsapp)|"
        r"bypass\s+(?:2fa|two[- ]factor|paywall)|"
        r"crack\s+(?:license|password|account)|"
        r"ddos\s+(?:attack|service)|"
        r"(?:gain|get|obtain|give\s+me|grant)\s+unauthorized\s+access\s+to)\b",
        re.I,
    )),
    ("carding_fraud", re.compile(
        r"\b(?:carding|cvv\s*shop|fullz|stolen\s+credit\s*cards?|"
        r"fake\s+(?:id|passport|diploma)s?\b)",
        re.I,
    )),
]


@dataclass(frozen=True)
class ComplianceVerdict:
    allowed: bool
    reason: str = ""
    category: str = ""


_DEFENSIVE = re.compile(
    r"\b(?:prevent|block|stop|defend|protect|guard|mitigate|harden|"
    r"detect|secure|against|restrict|limit(?:ing|ed)?|ensure|"
    r"can(?:not|'t| not))\b",
    re.I,
)


def check_tos_compliance(text: str) -> ComplianceVerdict:
    """Return allowed=False when job clearly violates marketplace ToS."""
    if not text or not text.strip():
        return ComplianceVerdict(allowed=True)
    for category, pattern in _PROHIBITED:
        m = pattern.search(text)
        if m:
            # Defensive-security posts legitimately mention attack phrases
            # ("prevent unauthorized access", "stop users bypassing 2fa"). If a
            # defensive verb sits just before the match, treat it as allowed.
            if category == "hacking_hire":
                window = text[max(0, m.start() - 60):m.start()]
                if _DEFENSIVE.search(window):
                    continue
            return ComplianceVerdict(
                allowed=False,
                category=category,
                reason=f"TOS violation ({category}): matched '{m.group(0)[:80]}'",
            )
    return ComplianceVerdict(allowed=True)
