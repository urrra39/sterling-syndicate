"""Compliance firewall + sandbox + DLQ backoff tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.compliance import check_tos_compliance
from app.services.dlq import backoff_seconds, enqueue, process_due, register_handler
from app.services.sandbox import run_in_sandbox


def test_blocks_academic_fraud() -> None:
    v = check_tos_compliance("Please write my thesis on climate change for $200")
    assert v.allowed is False
    assert v.category == "academic_fraud"


def test_blocks_malware() -> None:
    v = check_tos_compliance("Need someone to build a ransomware tool for Windows")
    assert v.allowed is False
    assert v.category == "malware"


def test_blocks_hacking_hire() -> None:
    v = check_tos_compliance("Can you hack into someone's Instagram account?")
    assert v.allowed is False


def test_allows_normal_dev_job() -> None:
    v = check_tos_compliance("Need a FastAPI developer to build a CRM dashboard with React")
    assert v.allowed is True


def test_sandbox_runs_safe_code() -> None:
    r = run_in_sandbox("print(2 + 2)\n")
    assert r.timed_out is False
    assert r.engine in {"docker", "subprocess"}
    if r.engine != "unavailable":
        assert r.ok is True
        assert "4" in r.stdout


def test_sandbox_timeout_kills_infinite_loop() -> None:
    r = run_in_sandbox("while True:\n    pass\n", timeout_sec=2)
    assert r.timed_out is True
    assert r.ok is False


def test_backoff_exponential() -> None:
    assert backoff_seconds(1) == 30
    assert backoff_seconds(2) == 60
    assert backoff_seconds(3) == 120
    assert backoff_seconds(5) == 480


class _FakeDB:
    """Minimal stand-in for enqueue/process_due unit tests."""

    def __init__(self):
        self.added = []
        self._leads = {}

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        pass

    def commit(self):
        pass

    def get(self, model, pk):
        return self._leads.get(pk)


def test_dlq_exhausts_after_5_and_alerts(monkeypatch: pytest.MonkeyPatch) -> None:
    alerts: list[dict] = []
    monkeypatch.setattr(
        "app.services.dlq.notify_api_outage",
        lambda **kw: alerts.append(kw),
    )

    calls = {"n": 0}

    def always_fail(_payload):
        calls["n"] += 1
        raise RuntimeError("provider timeout")

    register_handler("test_fail", always_fail)

    # Build a real-ish task object and drive _retry_one via process_due fake
    from app.services import dlq as dlq_mod

    task = SimpleNamespace(
        id=uuid4(),
        task_type="test_fail",
        payload_json="{}",
        attempts=4,
        max_attempts=5,
        status="pending",
        next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        last_error=None,
    )

    class _DB:
        def flush(self):
            pass

        def commit(self):
            pass

        def scalars(self, _stmt):
            return SimpleNamespace(all=lambda: [task])

    dlq_mod.process_due(_DB(), limit=1)
    assert task.attempts == 5
    assert task.status == "exhausted"
    assert len(alerts) == 1
    assert alerts[0]["attempts"] == 5


def test_dlq_succeeds_marks_done(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.dlq.notify_api_outage", lambda **kw: None)
    register_handler("test_ok", lambda p: None)
    from app.services import dlq as dlq_mod

    task = SimpleNamespace(
        id=uuid4(),
        task_type="test_ok",
        payload_json="{}",
        attempts=0,
        max_attempts=5,
        status="pending",
        next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        last_error="old",
    )

    class _DB:
        def flush(self):
            pass

        def commit(self):
            pass

        def scalars(self, _stmt):
            return SimpleNamespace(all=lambda: [task])

    dlq_mod.process_due(_DB(), limit=1)
    assert task.status == "done"
    assert task.last_error is None
