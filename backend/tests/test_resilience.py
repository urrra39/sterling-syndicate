from __future__ import annotations

from app.services.idempotency import content_hash, release, try_acquire
from app.services.semantic_extract import extract_job_fields, strip_html


def test_content_hash_stable_for_url() -> None:
    a = content_hash(user_id="u1", source="remoteok", url="https://X.com/job/1", raw_text="a")
    b = content_hash(user_id="u1", source="remoteok", url="https://x.com/job/1", raw_text="b")
    assert a == b  # URL wins over text


def test_content_hash_differs_by_user() -> None:
    a = content_hash(user_id="u1", source="manual", url=None, raw_text="same job")
    b = content_hash(user_id="u2", source="manual", url=None, raw_text="same job")
    assert a != b


def test_inflight_lock_is_exclusive() -> None:
    key = "abc" * 20 + "deadbeef"
    assert try_acquire(key) is True
    assert try_acquire(key) is False
    release(key)
    assert try_acquire(key) is True
    release(key)


def test_semantic_heuristic_budget() -> None:
    fields = extract_job_fields(
        "Job title: FastAPI engineer\nBudget: $4000\nBuild webhooks and admin UI.",
        hint_title="",
    )
    assert "FastAPI" in fields.title or "FastAPI" in fields.description
    assert fields.budget is not None


def test_strip_html() -> None:
    assert "Hello" in strip_html("<div><script>x</script>Hello <b>world</b></div>")
