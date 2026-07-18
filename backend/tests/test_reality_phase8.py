"""Phase 8 — CAPTCHA pause, dynamic sandbox profiles, SAST gate."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from app.models.lead import PipelineStatus
from app.services.browser_guard import (
    create_pause,
    html_looks_like_captcha,
    resume_pause,
    wait_for_resume,
)
from app.services.execution_agent import run_qa_agent
from app.services.sandbox import detect_language, profile_for_code
from app.services.sast import scan_code


def test_captcha_html_detected() -> None:
    assert html_looks_like_captcha("<div class='g-recaptcha'></div>") is not None
    assert html_looks_like_captcha("Please enter the SMS code to continue") is not None
    assert html_looks_like_captcha("<html><body>Hello world job board</body></html>") is None


def test_captcha_pause_and_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.browser_guard.notify_captcha_intervention",
        lambda **_kwargs: None,
    )
    pause = create_pause(reason="test captcha", page_url="https://example.test/challenge")
    assert pause.resolved is False

    done = {"ok": False}

    def waiter() -> None:
        done["ok"] = wait_for_resume(pause.pause_id, timeout_sec=5)

    t = threading.Thread(target=waiter, daemon=True)
    t.start()
    time.sleep(0.05)
    assert resume_pause(pause.pause_id) is True
    t.join(timeout=2)
    assert done["ok"] is True


def test_sandbox_python_profile_light() -> None:
    code = "def hello():\n    print(1)\n"
    assert detect_language(code) == "python"
    p = profile_for_code(code)
    assert p.memory == "512m"
    assert p.timeout_sec == 60
    assert p.language == "python"


def test_sandbox_node_heavy_profile() -> None:
    code = "```tsx\nimport React from 'react'\n// next.config\nnpm install\n```\n"
    assert detect_language(code) == "javascript"
    p = profile_for_code(code)
    assert p.memory == "4g"
    assert p.timeout_sec == 300
    assert p.language == "javascript"


def test_sandbox_rust_profile() -> None:
    code = "```rust\nfn main() { println!(\"hi\"); }\n```\n"
    assert detect_language(code) == "rust"
    p = profile_for_code(code)
    assert p.memory in {"2g", "4g"}
    assert p.timeout_sec == 300


def test_sast_rejects_sqli_and_secrets() -> None:
    bad = (
        'cursor.execute(f"SELECT * FROM users WHERE id={user_id}")\n'
        'api_key = "sk-live-supersecretkey123"\n'
    )
    report = scan_code(bad)
    assert report.passed is False
    assert any(f.severity == "error" for f in report.findings)
    assert "sql" in report.error_log.lower() or "secret" in report.error_log.lower()


def test_sast_passes_clean_code() -> None:
    clean = "def add(a: int, b: int) -> int:\n    return a + b\n"
    report = scan_code(clean)
    assert report.passed is True


def test_qa_blocks_ready_for_delivery_on_sast_fail() -> None:
    guard = SimpleNamespace(
        contract=SimpleNamespace(
            max_api_budget=10.0,
            cumulative_api_cost=0.0,
            status="in_progress",
            execution_draft="",
            completeness_pct=0.0,
            emergency_extensions=0,
        ),
        charge=lambda *_a, **_k: None,
    )
    bad = 'eval(user_input)\ncursor.execute(f"SELECT {x}")\n'
    review = run_qa_agent(guard, draft=bad, requirements="Build a safe API")
    assert review is not None
    assert review.sast_passed is False
    assert review.ready_for_delivery is False
    assert review.passed is False
    assert "SAST" in review.issues or "rejected_by_sast" in review.summary


def test_qa_fail_closed_when_charge_raises() -> None:
    """Profit Guard 402 (or any charge error) must NOT advertise ready_for_delivery.

    Trigger: SAST-clean draft, remaining budget too small for the QA meter charge.
    charge() raises HTTPException(402); the outer handler must fail closed.
    """
    from fastapi import HTTPException, status

    def _charge_blows_up(*_a, **_k):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="PROFIT GUARD CIRCUIT BREAKER",
        )

    guard = SimpleNamespace(
        contract=SimpleNamespace(
            max_api_budget=1.0,
            cumulative_api_cost=0.999,
            status="active",
            execution_draft="",
            completeness_pct=70.0,
            emergency_extensions=0,
        ),
        charge=_charge_blows_up,
    )
    clean = (
        "def add(a: int, b: int) -> int:\n"
        "    return a + b\n\n"
        "def main() -> None:\n"
        "    print(add(2, 2))\n"
    )
    review = run_qa_agent(guard, draft=clean, requirements="Implement add()")
    assert review is not None
    assert review.ready_for_delivery is False
    assert review.passed is False
    assert "fail_closed" in review.summary or "failed" in review.issues.lower()


def test_pipeline_status_enums_exist() -> None:
    assert PipelineStatus.PAUSED_FOR_CAPTCHA.value == "paused_for_captcha"
    assert PipelineStatus.REJECTED_BY_SAST.value == "rejected_by_sast"
