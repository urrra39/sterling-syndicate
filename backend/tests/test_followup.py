"""Follow-up (48h) + archive (7d) timeout logic."""

from __future__ import annotations

from app.services.followup import (
    polite_follow_up_body,
    should_archive,
    should_draft_follow_up,
)


def test_follow_up_after_48h() -> None:
    assert should_draft_follow_up(
        status="sent",
        hours_silent=48.0,
        has_follow_up=False,
        follow_up_after_hours=48.0,
    )
    assert not should_draft_follow_up(
        status="sent",
        hours_silent=47.9,
        has_follow_up=False,
        follow_up_after_hours=48.0,
    )


def test_no_duplicate_follow_up() -> None:
    assert not should_draft_follow_up(
        status="negotiating",
        hours_silent=100.0,
        has_follow_up=True,
        follow_up_after_hours=48.0,
    )


def test_follow_up_only_sent_or_negotiating() -> None:
    assert not should_draft_follow_up(
        status="new",
        hours_silent=100.0,
        has_follow_up=False,
        follow_up_after_hours=48.0,
    )
    assert not should_draft_follow_up(
        status="in_progress",
        hours_silent=100.0,
        has_follow_up=False,
        follow_up_after_hours=48.0,
    )


def test_archive_after_7_days() -> None:
    assert should_archive(
        status="sent",
        hours_silent=7 * 24,
        archive_after_hours=7 * 24,
    )
    assert not should_archive(
        status="sent",
        hours_silent=7 * 24 - 1,
        archive_after_hours=7 * 24,
    )


def test_never_archive_paid_or_in_progress() -> None:
    for status in (
        "won",
        "in_progress",
        "pending_payment_verification",
        "paused_for_budget_extension",
        "delivered",
        "paid",
        "archived",
    ):
        assert not should_archive(
            status=status,
            hours_silent=9999,
            archive_after_hours=7 * 24,
        )


def test_polite_follow_up_mentions_title() -> None:
    body = polite_follow_up_body(lead_title="Acme API", user_name="Alex")
    assert "Acme API" in body
    assert "Alex" in body
    assert "inbox" in body.lower() or "questions" in body.lower()
