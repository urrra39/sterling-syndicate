from __future__ import annotations

"""Pre-delivery SAST — lightweight static scan before ready_for_delivery.

Uses Semgrep when installed; otherwise a deterministic pattern scanner
(SQLi, XSS, secrets, eval/exec). Blocks poisoned RAG snippets from shipping.
"""

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class SastFinding:
    rule_id: str
    severity: str  # error | warning
    message: str
    line: int = 0


@dataclass
class SastReport:
    passed: bool
    engine: str  # semgrep | builtin
    findings: List[SastFinding] = field(default_factory=list)

    @property
    def error_log(self) -> str:
        if not self.findings:
            return ""
        lines = [f"[{f.severity}] {f.rule_id}: {f.message}" + (f" (L{f.line})" if f.line else "") for f in self.findings]
        return "\n".join(lines)


_BUILTIN_RULES = [
    ("sql_injection_format", "error", re.compile(r"""(?:execute|cursor\.execute)\s*\(\s*(?:f["']|["'].*%|["'].*\.format)""", re.I), "Possible SQL injection via string formatting"),
    ("sql_injection_fstring", "error", re.compile(r"""(?i)f["'].*\b(?:select|insert|update|delete)\b.*\{""", re.I), "SQL built via f-string interpolation"),
    ("sql_injection_concat", "error", re.compile(r"""(?:SELECT|INSERT|UPDATE|DELETE).*(?:\+|%\s*\(|\.format\()""", re.I), "SQL built via string concat/format"),
    ("xss_innerhtml", "error", re.compile(r"""\.innerHTML\s*=|dangerouslySetInnerHTML""", re.I), "XSS sink: innerHTML / dangerouslySetInnerHTML"),
    ("eval_exec", "error", re.compile(r"""\b(?:eval|exec)\s*\(|new\s+Function\s*\(""", re.I), "Dangerous eval/exec/Function"),
    ("pickle_load", "error", re.compile(r"""\bpickle\.loads?\s*\(""", re.I), "Insecure pickle deserialization"),
    ("subprocess_shell", "error", re.compile(r"""subprocess\.(?:call|run|Popen)\([^)]*shell\s*=\s*True""", re.I), "subprocess with shell=True"),
    ("hardcoded_secret", "error", re.compile(r"""(?i)(?:api[_-]?key|secret[_-]?key|password|aws_secret)\s*=\s*['"][^'"]{8,}['"]"""), "Possible hardcoded secret"),
    ("private_key", "error", re.compile(r"""-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"""), "Embedded private key material"),
    ("md5_password", "warning", re.compile(r"""hashlib\.md5\s*\(.*password|md5\s*\(.*password""", re.I), "Weak MD5 for password hashing"),
]


def scan_code(code: str, *, filename: str = "draft.py") -> SastReport:
    """Scan draft code. Fail-closed on error-severity findings."""
    if not (code or "").strip():
        return SastReport(passed=False, engine="builtin", findings=[
            SastFinding("empty_draft", "error", "No code to scan", 0)
        ])

    if shutil.which("semgrep"):
        report = _scan_semgrep(code, filename=filename)
        if report is not None:
            return report
    return _scan_builtin(code)


def _scan_builtin(code: str) -> SastReport:
    findings: List[SastFinding] = []
    for i, line in enumerate(code.splitlines(), 1):
        for rule_id, severity, pat, msg in _BUILTIN_RULES:
            if pat.search(line):
                findings.append(SastFinding(rule_id, severity, msg, i))
    # Also scan whole-file for multiline patterns
    for rule_id, severity, pat, msg in _BUILTIN_RULES:
        if any(f.rule_id == rule_id for f in findings):
            continue
        if pat.search(code):
            findings.append(SastFinding(rule_id, severity, msg, 0))
    errors = [f for f in findings if f.severity == "error"]
    return SastReport(passed=len(errors) == 0, engine="builtin", findings=findings)


def _scan_semgrep(code: str, *, filename: str) -> Optional[SastReport]:
    with tempfile.TemporaryDirectory(prefix="pp-sast-") as tmp:
        path = Path(tmp) / filename
        path.write_text(code, encoding="utf-8")
        try:
            proc = subprocess.run(
                [
                    "semgrep",
                    "--config",
                    "p/owasp-top-ten",
                    "--json",
                    "--quiet",
                    str(path),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
        except Exception:
            return None
        try:
            data = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            return None
        findings: List[SastFinding] = []
        for r in data.get("results") or []:
            findings.append(
                SastFinding(
                    rule_id=str(r.get("check_id") or "semgrep"),
                    severity="error" if str(r.get("extra", {}).get("severity", "")).lower() in {"error", "high"} else "warning",
                    message=str((r.get("extra") or {}).get("message") or r.get("check_id") or "finding"),
                    line=int(((r.get("start") or {}).get("line") or 0)),
                )
            )
        errors = [f for f in findings if f.severity == "error"]
        return SastReport(passed=len(errors) == 0, engine="semgrep", findings=findings)
