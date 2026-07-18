from __future__ import annotations

"""Execution_Agent (elite) + QA_Agent (Sonnet) with Profit Guard.

Activated only when is_payment_verified. Never auto-delivers to clients —
output stays as execution_draft until human marks deliverables.
"""

from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, Field

from app.models.lead import Lead, PipelineStatus
from app.models.proposal import Contract
from app.services.llm_router import LLMError, TaskKind, complete_json, complete_text
from app.services.profit_guard import (
    BudgetState,
    ProfitGuard,
    TokenUsage,
    estimate_cost,
    init_budget,
)
from app.services.prompt_guard import wrap_untrusted


class QAReview(BaseModel):
    passed: bool
    completeness_pct: float = Field(ge=0, le=100)
    issues: str = ""
    authorize_emergency_extension: bool = False
    summary: str = ""
    sast_passed: bool = True
    sast_log: str = ""
    ready_for_delivery: bool = False


@dataclass
class ExecutionResult:
    draft: str
    model_used: str
    cost_this_run: float
    cumulative_api_cost: float
    max_api_budget: float
    budget_state: str
    qa: Optional[QAReview]
    paused: bool
    message: str
    sast_passed: bool = True
    ready_for_delivery: bool = False


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _complete_metered(
    guard: ProfitGuard,
    *,
    system: str,
    user: str,
    model: str,
    max_tokens: int = 2500,
) -> str:
    """Run one completion, charge ProfitGuard, return text. Raises 402 if blocked."""
    # Pre-flight: refuse unless remaining budget covers the WORST-CASE call. The
    # provider bills for actual output up to max_tokens, so gating on a smaller
    # estimate let a call whose real cost overshoots the cap slip through.
    projected = estimate_cost(model, _approx_tokens(system + user), max_tokens)
    if projected > float(guard.contract.max_api_budget) - float(
        guard.contract.cumulative_api_cost
    ):
        guard.save_draft(guard.contract.execution_draft or "", guard.contract.completeness_pct or 0)
        guard._pause(
            completeness=guard.contract.completeness_pct or 0.0,
            reason="insufficient_for_next_call",
        )
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="PROFIT GUARD: remaining budget too small for next elite call. Paused.",
        )

    # Route: opus/sonnet → anthropic path via TaskKind; gpt → creative/openai
    kind = TaskKind.ANALYTICAL if "claude" in model.lower() or "llama" in model.lower() else TaskKind.CREATIVE
    try:
        text = complete_text(
            system=system,
            user=user,
            kind=kind,
            temperature=0.2 if kind == TaskKind.ANALYTICAL else 0.35,
            max_tokens=max_tokens,
        )
    except LLMError:
        # Offline / no keys: deterministic scaffold so pipeline + guard still testable
        text = (
            f"# Execution draft ({model})\n\n"
            f"## Scope\n{user[:800]}\n\n"
            "## Implementation outline\n"
            "1. Scaffold modules from requirements\n"
            "2. Core logic stubs\n"
            "3. Tests + README\n\n"
            "(LLM unavailable — placeholder draft saved under Profit Guard.)\n"
        )

    usage = TokenUsage(
        input_tokens=_approx_tokens(system + user),
        output_tokens=_approx_tokens(text),
        model=model,
    )
    state = guard.charge(usage)
    if state in {BudgetState.EXHAUSTED, BudgetState.PAUSED}:
        # charge() already paused; still return text so draft is saved
        pass
    return text


def run_execution_agent(
    *,
    contract: Contract,
    lead: Lead,
    task_prompt: str = "",
    run_qa: bool = True,
) -> ExecutionResult:
    """Heavy-lifter generation + optional QA loop. Payment + budget gated."""
    if not contract.is_payment_verified:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Execution_Agent requires is_payment_verified=True",
        )

    if contract.max_api_budget <= 0:
        init_budget(contract)

    guard = ProfitGuard(contract, lead)
    cost_before = float(contract.cumulative_api_cost)

    try:
        model = guard.assert_can_run()
    except Exception:
        return ExecutionResult(
            draft=contract.execution_draft or "",
            model_used="",
            cost_this_run=0.0,
            cumulative_api_cost=float(contract.cumulative_api_cost),
            max_api_budget=float(contract.max_api_budget),
            budget_state=BudgetState.PAUSED.value
            if contract.status == "paused_for_budget_extension"
            else BudgetState.EXHAUSTED.value,
            qa=None,
            paused=True,
            message="Execution blocked by Profit Guard — authorize extension or review draft.",
        )

    safe_scope = wrap_untrusted("SCOPE", contract.agreed_scope)
    safe_task = wrap_untrusted("TASK", task_prompt or lead.raw_text[:4000])
    prior = contract.execution_draft or ""

    from app.services.secrets_scrubber import scrub_for_llm

    # ZERO-TRUST: never send raw secrets from client paste / RAG into Execution LLM
    safe_scope = scrub_for_llm(safe_scope)
    safe_task = scrub_for_llm(safe_task)
    prior = scrub_for_llm(prior)

    system = (
        "You are Execution_Agent for The Sterling Syndicate — an elite implementation agent. "
        "Produce concrete, production-oriented code/scaffolding for the agreed scope. "
        "Do not claim work was delivered to the client. Output is a draft for human review. "
        "No chain-of-thought preamble."
    )
    user = (
        f"Project: {lead.title}\n"
        f"Agreed scope:\n{safe_scope}\n"
        f"Task / requirements:\n{safe_task}\n"
        f"Prior draft (continue/improve if present):\n{prior[:6000]}\n"
    )

    try:
        draft = _complete_metered(guard, system=system, user=user, model=model, max_tokens=3000)
    except Exception as exc:
        from fastapi import HTTPException

        if isinstance(exc, HTTPException):
            guard.save_draft(prior, contract.completeness_pct or 0)
            return ExecutionResult(
                draft=prior,
                model_used=model,
                cost_this_run=0.0,
                cumulative_api_cost=float(contract.cumulative_api_cost),
                max_api_budget=float(contract.max_api_budget),
                budget_state=BudgetState.PAUSED.value,
                qa=None,
                paused=True,
                message=str(exc.detail),
            )
        raise

    guard.save_draft(draft, completeness=55.0 if not prior else 70.0)
    qa_result: Optional[QAReview] = None
    paused = contract.status == "paused_for_budget_extension"
    message = f"Execution draft saved via {model}."

    if run_qa and not paused:
        qa_result = run_qa_agent(guard, draft=draft, requirements=contract.agreed_scope)
        if qa_result:
            if not qa_result.sast_passed:
                contract.qa_status = "rejected_by_sast"
                lead.pipeline_status = PipelineStatus.REJECTED_BY_SAST.value
                message = (
                    "SAST rejected draft (poisoned/vulnerable patterns). "
                    "Forcing secure rewrite with SAST findings."
                )
                try:
                    model2 = guard.assert_can_run()
                    rev_system = (
                        system
                        + " SECURITY REWRITE: remove all vulnerabilities listed. "
                        "No eval/exec, no SQL string concat, no hardcoded secrets, no XSS sinks."
                    )
                    rev_user = (
                        user
                        + f"\nSAST findings (must fix):\n{qa_result.sast_log}\n"
                        + f"QA issues:\n{qa_result.issues}\n"
                    )
                    draft = _complete_metered(
                        guard, system=rev_system, user=rev_user, model=model2, max_tokens=2500
                    )
                    guard.save_draft(draft, max(qa_result.completeness_pct, 40.0))
                    qa_result = run_qa_agent(
                        guard, draft=draft, requirements=contract.agreed_scope
                    )
                    if qa_result and qa_result.sast_passed and qa_result.passed:
                        contract.qa_status = "ready_for_delivery"
                        if lead.pipeline_status == PipelineStatus.REJECTED_BY_SAST.value:
                            lead.pipeline_status = PipelineStatus.IN_PROGRESS.value
                        message = "Secure rewrite passed SAST + QA — ready_for_delivery."
                    elif qa_result and not qa_result.sast_passed:
                        contract.qa_status = "rejected_by_sast"
                        message = "Rewrite still fails SAST — human review required."
                    elif qa_result:
                        contract.qa_status = "rejected" if not qa_result.passed else "passed"
                except Exception:
                    paused = True
                    message = "SAST rewrite blocked by Profit Guard."
            else:
                contract.qa_status = (
                    "ready_for_delivery"
                    if qa_result.ready_for_delivery
                    else ("passed" if qa_result.passed else "rejected")
                )
                contract.completeness_pct = qa_result.completeness_pct
                if (
                    not qa_result.passed
                    and qa_result.authorize_emergency_extension
                    and (contract.emergency_extensions or 0) < 2
                ):
                    guard.authorize_extension()
                    message = (
                        f"QA rejected draft ({qa_result.completeness_pct:.0f}% complete). "
                        "Emergency +5% budget authorized for one revision."
                    )
                    try:
                        model2 = guard.assert_can_run()
                        rev_system = system + " Revise to address QA issues. Keep changes focused."
                        rev_user = user + f"\nQA issues:\n{qa_result.issues}\n"
                        draft = _complete_metered(
                            guard, system=rev_system, user=rev_user, model=model2, max_tokens=2500
                        )
                        guard.save_draft(draft, qa_result.completeness_pct + 10)
                        qa_result = run_qa_agent(
                            guard, draft=draft, requirements=contract.agreed_scope
                        )
                        if qa_result:
                            if not qa_result.sast_passed:
                                contract.qa_status = "rejected_by_sast"
                                lead.pipeline_status = PipelineStatus.REJECTED_BY_SAST.value
                            else:
                                contract.qa_status = (
                                    "ready_for_delivery"
                                    if qa_result.ready_for_delivery
                                    else ("passed" if qa_result.passed else "rejected")
                                )
                            contract.completeness_pct = qa_result.completeness_pct
                    except Exception:
                        paused = True
                        message = "Revision blocked by Profit Guard after QA extension."
                elif not qa_result.passed and qa_result.completeness_pct < 90:
                    if budget_near_limit(contract):
                        guard._pause(
                            completeness=qa_result.completeness_pct,
                            reason="qa_incomplete_at_budget",
                        )
                        paused = True
                        message = (
                            f"Budget limit / QA incomplete ({qa_result.completeness_pct:.0f}%). "
                            "Paused — authorize extra 5% or review draft."
                        )
                    else:
                        message = f"QA rejected — {qa_result.summary}"

    paused = paused or contract.status == "paused_for_budget_extension"
    ready = bool(qa_result and qa_result.ready_for_delivery and qa_result.sast_passed)
    return ExecutionResult(
        draft=contract.execution_draft or draft,
        model_used=model,
        cost_this_run=round(float(contract.cumulative_api_cost) - cost_before, 6),
        cumulative_api_cost=float(contract.cumulative_api_cost),
        max_api_budget=float(contract.max_api_budget),
        budget_state=guard_state_str(contract),
        qa=qa_result,
        paused=paused,
        message=message,
        sast_passed=bool(qa_result.sast_passed) if qa_result else True,
        ready_for_delivery=ready,
    )


def budget_near_limit(contract: Contract) -> bool:
    if contract.max_api_budget <= 0:
        return True
    return float(contract.cumulative_api_cost) / float(contract.max_api_budget) >= 0.9


def guard_state_str(contract: Contract) -> str:
    from app.services.profit_guard import budget_state

    return budget_state(contract).value


def run_qa_agent(guard: ProfitGuard, *, draft: str, requirements: str) -> Optional[QAReview]:
    """QA + mandatory SAST — never ready_for_delivery until SAST passes."""
    from app.services.sast import scan_code
    from app.services.secrets_scrubber import scrub_for_llm

    # ZERO-TRUST: scrub BEFORE any LLM hop (requirements/draft may contain pasted secrets)
    safe_draft = scrub_for_llm(draft)
    safe_requirements = scrub_for_llm(requirements)

    sast = scan_code(safe_draft)
    if not sast.passed:
        return QAReview(
            passed=False,
            completeness_pct=50.0,
            issues=f"SAST rejected:\n{sast.error_log}",
            authorize_emergency_extension=True,
            summary="rejected_by_sast",
            sast_passed=False,
            sast_log=sast.error_log,
            ready_for_delivery=False,
        )

    model = "claude-sonnet-5"
    system = (
        "You are QA_Agent for The Sterling Syndicate. Review the draft against requirements. "
        "JSON only. If incomplete/buggy, set passed=false. "
        "Set authorize_emergency_extension=true only if a small revision would finish the job. "
        "SAST already passed — focus on completeness vs requirements."
    )
    user = (
        f"Requirements:\n{safe_requirements[:3000]}\n\nDraft:\n{safe_draft[:8000]}\n"
    )
    try:
        # Pre-flight: if the contract is already at/over cap, never make a paid QA
        # call (that spend would bypass the guard). Route to the free offline
        # heuristic instead so accounting stays honest and the cap holds.
        from app.services.profit_guard import BudgetState, budget_state

        over_budget = budget_state(guard.contract) in {
            BudgetState.EXHAUSTED,
            BudgetState.PAUSED,
        }
        try:
            if over_budget:
                raise LLMError("budget exhausted — QA runs offline")
            review = complete_json(
                system=system,
                user=user,
                schema=QAReview,
                kind=TaskKind.ANALYTICAL,
            )
        except LLMError:
            incomplete = len(draft) < 200 or "TODO" in draft or "placeholder" in draft.lower()
            pct = 40.0 if incomplete else 88.0
            review = QAReview(
                passed=not incomplete,
                completeness_pct=pct,
                issues="Draft too short or contains placeholders" if incomplete else "",
                authorize_emergency_extension=incomplete,
                summary="offline heuristic QA",
            )
        review.sast_passed = True
        review.sast_log = sast.error_log or "SAST clean"
        review.ready_for_delivery = bool(review.passed and review.sast_passed)
        # Only charge for a real metered LLM call. When over budget we used the
        # free offline heuristic above, so there is nothing to charge.
        if not over_budget:
            usage = TokenUsage(
                input_tokens=_approx_tokens(system + user),
                output_tokens=120,
                model=model,
            )
            guard.charge(usage)
        return review
    except Exception:
        # Fail-closed: never mark ready_for_delivery when QA/metering blows up.
        # The previous fail-open (passed=True, ready_for_delivery=True) let a
        # ProfitGuard 402 from charge() — or any unexpected error — advertise
        # the draft as delivery-ready even though review never completed.
        return QAReview(
            passed=False,
            completeness_pct=0.0,
            issues="QA review failed; delivery blocked pending human review.",
            authorize_emergency_extension=False,
            summary="qa_error_fail_closed",
            sast_passed=True,
            sast_log=sast.error_log or "SAST clean",
            ready_for_delivery=False,
        )
