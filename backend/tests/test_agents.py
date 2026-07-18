from __future__ import annotations

from app.services.agents import negotiator_drafts, scout_filter_and_score, writer_draft_proposal


def test_scout_fallback_without_llm() -> None:
    score = scout_filter_and_score(
        lead_text="Looking for a FastAPI Python engineer with PostgreSQL",
        portfolio_blob="Senior Python FastAPI engineer. PostgreSQL, Docker.",
        skills=["python", "fastapi", "postgresql"],
    )
    assert 0.0 <= score.match_score <= 1.0
    assert isinstance(score.should_pursue, bool)


def test_writer_fallback_returns_draft() -> None:
    text, chunks, price = writer_draft_proposal(
        lead_text="Need FastAPI billing webhooks and React admin",
        name="Alex",
        skills=["python", "fastapi", "react"],
        portfolio_summary="Ships FastAPI backends",
        tone="confident",
        writer_instructions="Cite evidence.",
        user_id="test-user",
    )
    assert "Alex" in text
    assert price.recommended_bid > 0
    assert isinstance(chunks, list)


def test_negotiator_returns_three_drafts() -> None:
    drafts = negotiator_drafts(
        lead_text="Build an API",
        incoming="Can you do it for half price?",
        name="Alex",
        skills=["python"],
        negotiator_instructions="Hold firm.",
        floor_price=500,
    )
    assert len(drafts) >= 3
    assert all(d["body"] for d in drafts)


def test_negotiator_scope_creep_proposes_extension() -> None:
    drafts = negotiator_drafts(
        lead_text="Build a simple CRUD API",
        incoming="Also add a full admin dashboard and mobile app for free while you're at it",
        name="Alex",
        skills=["python"],
        negotiator_instructions="Defend scope.",
        floor_price=800,
        agreed_scope="REST CRUD API for inventory. No UI. No mobile.",
        agreed_price=800,
    )
    assert any(d.get("scope_creep_detected") == "true" for d in drafts)
    creep = next(d for d in drafts if d.get("scope_creep_detected") == "true")
    assert "scope" in creep["body"].lower() or "extension" in creep["label"].lower()
    assert "free" in creep["body"].lower() or "change order" in creep["body"].lower() or "extension" in creep["body"].lower()


def test_negotiator_in_scope_no_creep_flag() -> None:
    drafts = negotiator_drafts(
        lead_text="Build a CRUD API",
        incoming="Sounds good — when can we start on the inventory endpoints?",
        name="Alex",
        skills=["python"],
        negotiator_instructions="Defend scope.",
        agreed_scope="REST CRUD API for inventory. No UI.",
        agreed_price=800,
    )
    assert not any(d.get("scope_creep_detected") == "true" for d in drafts)
