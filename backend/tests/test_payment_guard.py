"""Payment authorization kill switch — unit tests (no DB required for core logic)."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services.payment_guard import (
    PAYMENT_LOCK_DETAIL,
    assert_payment_cleared,
    confirm_payment_received,
    is_payment_locked,
    lock_for_payment_verification,
)


class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self, _stmt):
        return self._value


def test_no_contract_is_not_locked() -> None:
    db = _FakeScalarResult(None)
    assert is_payment_locked(db, uuid4()) is False


def test_unverified_pending_contract_is_locked() -> None:
    contract = SimpleNamespace(
        status="pending_payment_verification",
        is_payment_verified=False,
    )
    db = _FakeScalarResult(contract)
    assert is_payment_locked(db, uuid4()) is True


def test_verified_contract_is_cleared() -> None:
    contract = SimpleNamespace(
        status="active",
        is_payment_verified=True,
    )
    db = _FakeScalarResult(contract)
    assert is_payment_locked(db, uuid4()) is False


def test_active_but_unverified_fail_closed() -> None:
    """Fail-closed: even 'active' without verification flag stays locked."""
    contract = SimpleNamespace(
        status="active",
        is_payment_verified=False,
    )
    db = _FakeScalarResult(contract)
    assert is_payment_locked(db, uuid4()) is True


def test_assert_raises_423_when_locked() -> None:
    contract = SimpleNamespace(
        status="pending_payment_verification",
        is_payment_verified=False,
    )
    db = _FakeScalarResult(contract)
    with pytest.raises(HTTPException) as exc:
        assert_payment_cleared(db, uuid4())
    assert exc.value.status_code == 423
    assert "KILL SWITCH" in exc.value.detail
    assert PAYMENT_LOCK_DETAIL in exc.value.detail


def test_assert_passes_when_cleared() -> None:
    contract = SimpleNamespace(
        status="active",
        is_payment_verified=True,
    )
    db = _FakeScalarResult(contract)
    assert_payment_cleared(db, uuid4())  # must not raise


def test_lock_sets_state_and_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    alerts: list[dict] = []

    def _fake_notify(**kwargs):
        alerts.append(kwargs)

    monkeypatch.setattr(
        "app.services.payment_guard.notify_payment_action_required",
        _fake_notify,
    )
    lead = SimpleNamespace(id=uuid4(), title="Acme API", pipeline_status="won")
    contract = SimpleNamespace(
        status="active",
        is_payment_verified=True,
        payment_claimed_at=None,
        client_display_name=None,
        agreed_price=1500.0,
        currency="USD",
    )
    lock_for_payment_verification(
        None,  # type: ignore[arg-type]
        lead=lead,
        contract=contract,
        client_name="Acme Corp",
        amount=1500.0,
        send_alert=True,
    )
    assert contract.status == "pending_payment_verification"
    assert contract.is_payment_verified is False
    assert contract.client_display_name == "Acme Corp"
    assert lead.pipeline_status == "pending_payment_verification"
    assert len(alerts) == 1
    assert alerts[0]["client_name"] == "Acme Corp"
    assert alerts[0]["amount"] == 1500.0


def test_confirm_unlocks() -> None:
    lead = SimpleNamespace(
        pipeline_status="pending_payment_verification",
    )
    contract = SimpleNamespace(
        status="pending_payment_verification",
        is_payment_verified=False,
        payment_verified_at=None,
        agreed_scope="simple bug fix",
        agreed_price=1000.0,
        effort_level="medium",
        max_api_budget=0.0,
        cumulative_api_cost=0.0,
        emergency_extensions=0,
    )
    confirm_payment_received(None, lead=lead, contract=contract)  # type: ignore[arg-type]
    assert contract.is_payment_verified is True
    assert contract.status == "active"
    assert lead.pipeline_status == "in_progress"
    assert contract.payment_verified_at is not None
    assert contract.max_api_budget > 0
