from __future__ import annotations

"""Zero-Trust local scrubber — mask secrets/PII BEFORE any LLM API call.

Runs entirely in-process. Never forwards raw credentials to OpenAI/Anthropic.
Optional Microsoft Presidio when installed; deterministic regex otherwise.
"""

import re
from dataclasses import dataclass, field
from typing import List, Optional, Pattern, Tuple


@dataclass(frozen=True)
class ScrubFinding:
    kind: str
    placeholder: str
    count: int = 1


@dataclass(frozen=True)
class ScrubResult:
    text: str
    findings: List[ScrubFinding] = field(default_factory=list)
    engine: str = "regex"

    @property
    def redacted(self) -> bool:
        return len(self.findings) > 0


# (kind, placeholder, pattern) — applied in order; longer/more specific first
_RULES: List[Tuple[str, str, Pattern[str]]] = [
    (
        "aws_access_key",
        "[REDACTED_AWS_KEY]",
        re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    ),
    (
        "aws_secret",
        "[REDACTED_AWS_SECRET]",
        re.compile(
            r"(?i)(?:aws_secret_access_key|secret_access_key)\s*[=:]\s*['\"]?([A-Za-z0-9/+=]{40})['\"]?"
        ),
    ),
    (
        "openai_key",
        "[REDACTED_OPENAI_KEY]",
        re.compile(r"\bsk-(?:proj-|live-|test-)?[A-Za-z0-9_-]{20,}\b"),
    ),
    (
        "anthropic_key",
        "[REDACTED_ANTHROPIC_KEY]",
        re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    ),
    (
        "github_token",
        "[REDACTED_GITHUB_TOKEN]",
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,}\b"),
    ),
    (
        "slack_token",
        "[REDACTED_SLACK_TOKEN]",
        re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    ),
    (
        "stripe_key",
        "[REDACTED_STRIPE_KEY]",
        re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{16,}\b"),
    ),
    (
        "jwt",
        "[REDACTED_JWT]",
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    ),
    (
        "private_key",
        "[REDACTED_PRIVATE_KEY]",
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
        ),
    ),
    (
        "connection_string",
        "[REDACTED_DB_URL]",
        re.compile(
            r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s'\"<>]+"
        ),
    ),
    (
        "generic_password",
        "[REDACTED_PASSWORD]",
        re.compile(
            r"(?i)\b(?:password|passwd|pwd|db_pass|database_password)\s*[=:]\s*['\"]?[^\s'\"<>]{6,}['\"]?"
        ),
    ),
    (
        "generic_api_secret",
        "[REDACTED_API_SECRET]",
        re.compile(
            r"(?i)\b(?:api[_-]?key|api[_-]?secret|secret[_-]?key|access[_-]?token)\s*[=:]\s*['\"]?[A-Za-z0-9_\-./+=]{12,}['\"]?"
        ),
    ),
    (
        "email",
        "[REDACTED_EMAIL]",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ),
    (
        "phone_intl",
        "[REDACTED_PHONE]",
        re.compile(r"(?<!\w)(?:\+|00)?(?:998|1|44|49|33|81|82|86)[\s\-.]?\d[\d\s\-.]{7,14}\b"),
    ),
    (
        "credit_card",
        "[REDACTED_CARD]",
        re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
    ),
]


def _luhn_ok(digits: str) -> bool:
    s = 0
    alt = False
    for ch in reversed(digits):
        n = ord(ch) - 48
        if alt:
            n *= 2
            if n > 9:
                n -= 9
        s += n
        alt = not alt
    return s % 10 == 0


def scrub_secrets(text: str, *, max_len: int = 50_000) -> ScrubResult:
    """Mask credentials/PII locally. Safe to send result.text to external LLMs."""
    if not text:
        return ScrubResult(text="", findings=[], engine="regex")

    working = text[:max_len]
    findings: List[ScrubFinding] = []
    engine = "regex"

    # Optional Presidio (PII) — never required
    presidio_out = _try_presidio(working)
    if presidio_out is not None:
        working, p_findings = presidio_out
        findings.extend(p_findings)
        engine = "presidio+regex"

    for kind, placeholder, pattern in _RULES:
        if kind == "credit_card":
            working, n = _scrub_cards(working, placeholder)
        elif kind == "aws_secret":
            # Replace full assignment, keep label context via placeholder only
            def _aws_sub(m: re.Match[str]) -> str:
                return m.group(0).split("=")[0].split(":")[0] + f"= {placeholder}"

            new_text, n = pattern.subn(_aws_sub, working)
            working = new_text
        else:
            new_text, n = pattern.subn(placeholder, working)
            working = new_text
        if n:
            findings.append(ScrubFinding(kind=kind, placeholder=placeholder, count=n))

    return ScrubResult(text=working, findings=findings, engine=engine)


def scrub_for_llm(text: str) -> str:
    """Convenience: return only scrubbed string (first middleware hop)."""
    from app.core.config import settings

    if not settings.secrets_scrubber_enabled:
        return text or ""
    return scrub_secrets(text).text


def _scrub_cards(text: str, placeholder: str) -> Tuple[str, int]:
    count = 0

    def repl(m: re.Match[str]) -> str:
        nonlocal count
        raw = re.sub(r"[^\d]", "", m.group(0))
        if 13 <= len(raw) <= 19 and _luhn_ok(raw):
            count += 1
            return placeholder
        return m.group(0)

    return re.sub(r"\b(?:\d[ -]*?){13,19}\b", repl, text), count


def _try_presidio(text: str) -> Optional[Tuple[str, List[ScrubFinding]]]:
    try:
        from presidio_analyzer import AnalyzerEngine  # type: ignore
        from presidio_anonymizer import AnonymizerEngine  # type: ignore
        from presidio_anonymizer.entities import OperatorConfig  # type: ignore
    except Exception:
        return None

    try:
        analyzer = AnalyzerEngine()
        anonymizer = AnonymizerEngine()
        results = analyzer.analyze(
            text=text,
            language="en",
            entities=["EMAIL_ADDRESS", "PHONE_NUMBER", "CREDIT_CARD", "IBAN_CODE", "PERSON"],
        )
        if not results:
            return text, []
        operators = {
            "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "[REDACTED_EMAIL]"}),
            "PHONE_NUMBER": OperatorConfig("replace", {"new_value": "[REDACTED_PHONE]"}),
            "CREDIT_CARD": OperatorConfig("replace", {"new_value": "[REDACTED_CARD]"}),
            "IBAN_CODE": OperatorConfig("replace", {"new_value": "[REDACTED_IBAN]"}),
            "PERSON": OperatorConfig("replace", {"new_value": "[REDACTED_PERSON]"}),
        }
        out = anonymizer.anonymize(text=text, analyzer_results=results, operators=operators)
        findings = [
            ScrubFinding(kind=f"presidio_{r.entity_type.lower()}", placeholder="presidio", count=1)
            for r in results
        ]
        return out.text, findings
    except Exception:
        return None
