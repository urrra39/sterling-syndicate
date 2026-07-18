"""Phase 9 — residential proxy posture + zero-trust secrets scrubber."""

from __future__ import annotations

import pytest

from app.services.playwright_stealth import (
    MarketplaceAutomationRefused,
    assert_url_allowed,
    playwright_proxy_dict,
    residential_proxy_config,
    stealth_init_script,
)
from app.services.secrets_scrubber import scrub_for_llm, scrub_secrets


def test_scrub_aws_and_openai_keys() -> None:
    raw = (
        "Deploy with AKIAIOSFODNN7EXAMPLE and sk-proj-abcdefghijklmnopqrstuvwxyz0123456789\n"
        "Also password=SuperSecretPass99\n"
    )
    r = scrub_secrets(raw)
    assert r.redacted is True
    assert "AKIAIOSFODNN7EXAMPLE" not in r.text
    assert "sk-proj-" not in r.text
    assert "[REDACTED_AWS_KEY]" in r.text
    assert "[REDACTED_OPENAI_KEY]" in r.text
    assert "[REDACTED_PASSWORD]" in r.text


def test_scrub_db_url_and_email() -> None:
    raw = "Connect postgres://admin:hunter2@db.internal:5432/app and mail me at boss@client.com"
    out = scrub_for_llm(raw)
    assert "hunter2" not in out
    assert "[REDACTED_DB_URL]" in out
    assert "[REDACTED_EMAIL]" in out
    assert "boss@client.com" not in out


def test_scrub_preserves_benign_text() -> None:
    raw = "Please add a login form and use parameterized queries for the users table."
    r = scrub_secrets(raw)
    assert r.text == raw
    assert r.redacted is False


def test_marketplace_url_refused() -> None:
    with pytest.raises(MarketplaceAutomationRefused):
        assert_url_allowed("https://www.upwork.com/nx/find-work/")
    with pytest.raises(MarketplaceAutomationRefused):
        assert_url_allowed("https://www.fiverr.com/login")
    assert_url_allowed("https://remoteok.com/remote-dev-jobs")  # allowed source


def test_proxy_required_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.playwright_stealth.settings.residential_proxy_url",
        "",
    )
    monkeypatch.setattr(
        "app.services.playwright_stealth.settings.residential_proxy_required",
        True,
    )
    with pytest.raises(RuntimeError, match="RESIDENTIAL_PROXY"):
        residential_proxy_config()


def test_proxy_dict_and_stealth_script(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.playwright_stealth.settings.residential_proxy_url",
        "http://proxy.example:8000",
    )
    monkeypatch.setattr(
        "app.services.playwright_stealth.settings.residential_proxy_username",
        "uz_user",
    )
    monkeypatch.setattr(
        "app.services.playwright_stealth.settings.residential_proxy_password",
        "secret",
    )
    monkeypatch.setattr(
        "app.services.playwright_stealth.settings.residential_proxy_required",
        False,
    )
    monkeypatch.setattr(
        "app.services.playwright_stealth.settings.residential_proxy_country",
        "UZ",
    )
    cfg = residential_proxy_config()
    assert cfg is not None
    assert cfg.country == "UZ"
    d = playwright_proxy_dict(cfg)
    assert d["server"] == "http://proxy.example:8000"
    assert d["username"] == "uz_user"
    script = stealth_init_script()
    assert "RTCPeerConnection" in script
    assert "webdriver" in script


def test_negotiator_scrubs_before_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure client-pasted secrets never appear in the LLM user payload."""
    from app.services import agents as agents_mod

    captured: dict = {}

    def fake_complete_json(**kwargs):
        captured["user"] = kwargs.get("user", "")
        from app.services.agent_schemas import NegotiationDrafts

        return NegotiationDrafts(
            hold_firm="Hold firm.",
            smaller_scope="Smaller scope.",
            clarifying_questions="Questions?",
            scope_creep_detected=False,
            out_of_scope_summary="",
            budget_extension_draft="",
            proposed_extension_amount=None,
        )

    monkeypatch.setattr(agents_mod, "provider_available", lambda *_a, **_k: True)
    monkeypatch.setattr(agents_mod.settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(agents_mod, "complete_json", fake_complete_json)

    secret = "AKIAIOSFODNN7EXAMPLE"
    agents_mod.negotiator_drafts(
        lead_text="Build an API",
        incoming=f"Here is my key {secret} please use it",
        name="Exec",
        skills=["Python"],
        negotiator_instructions="Be firm",
        floor_price=500,
    )
    assert secret not in captured.get("user", "")
    assert "[REDACTED_AWS_KEY]" in captured.get("user", "")
