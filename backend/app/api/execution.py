from __future__ import annotations

"""Execution hand-off + profit-guard budget extension endpoints."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.deps import CurrentUser, DbSession
from app.models.lead import Lead
from app.models.proposal import Contract
from app.schemas.crm import ContractPublic
from app.services.execution_agent import run_execution_agent
from app.services.output_sanitizer import sanitize_output
from app.services.payment_guard import assert_payment_cleared
from app.services.profit_guard import ProfitGuard, init_budget

router = APIRouter()


class ExecutionRequest(BaseModel):
    task_prompt: str = Field(default="", max_length=20000)
    run_qa: bool = True


class QAPublic(BaseModel):
    passed: bool
    completeness_pct: float
    issues: str = ""
    authorize_emergency_extension: bool = False
    summary: str = ""
    sast_passed: bool = True
    sast_log: str = ""
    ready_for_delivery: bool = False


class ExecutionResponse(BaseModel):
    draft: str
    model_used: str
    cost_this_run: float
    cumulative_api_cost: float
    max_api_budget: float
    budget_state: str
    effort_level: str
    qa: Optional[QAPublic] = None
    paused: bool
    message: str
    contract: ContractPublic
    sast_passed: bool = True
    ready_for_delivery: bool = False


class BudgetExtendRequest(BaseModel):
    extra_ratio: float = Field(default=0.05, gt=0, le=0.15)


class SandboxRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=200_000)
    language: str | None = Field(
        default=None,
        description="Optional override. Auto-detected from code when omitted.",
    )
    timeout_sec: int | None = Field(
        default=None,
        ge=1,
        le=300,
        description="Optional override. Profile default when omitted (≤300s).",
    )


class SandboxResponse(BaseModel):
    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    engine: str
    duration_ms: int
    language: str
    memory_mb: int
    timeout_sec: int


@router.post("/leads/{lead_id}/sandbox-eval", response_model=SandboxResponse)
def sandbox_eval(
    lead_id: UUID,
    payload: SandboxRequest,
    db: DbSession,
    user: CurrentUser,
) -> SandboxResponse:
    """Run agent code in DinD with dynamic RAM/timeout by language profile."""
    from app.services.sandbox import run_in_sandbox

    lead = db.get(Lead, lead_id)
    if lead is None or lead.user_id != user.id:
        raise HTTPException(status_code=404, detail="Lead not found")
    assert_payment_cleared(db, lead_id)
    contract = db.scalar(select(Contract).where(Contract.lead_id == lead_id))
    if contract is None or not contract.is_payment_verified:
        raise HTTPException(status_code=423, detail="Payment verification required")

    result = run_in_sandbox(
        payload.code,
        language=payload.language,
        timeout_sec=payload.timeout_sec,
    )
    return SandboxResponse(
        ok=result.ok,
        exit_code=result.exit_code,
        stdout=result.stdout,
        stderr=result.stderr,
        timed_out=result.timed_out,
        engine=result.engine,
        duration_ms=result.duration_ms,
        language=result.language,
        memory_mb=result.memory_mb,
        timeout_sec=result.timeout_sec,
    )


@router.post("/leads/{lead_id}/execute", response_model=ExecutionResponse)
def execute_project(
    lead_id: UUID,
    payload: ExecutionRequest,
    db: DbSession,
    user: CurrentUser,
) -> ExecutionResponse:
    """Run Execution_Agent — payment verified + profit guard enforced."""
    lead = db.get(Lead, lead_id)
    if lead is None or lead.user_id != user.id:
        raise HTTPException(status_code=404, detail="Lead not found")
    assert_payment_cleared(db, lead_id)

    contract = db.scalar(
        select(Contract)
        .where(Contract.lead_id == lead_id)
        .options(selectinload(Contract.deliverables))
        .with_for_update()
    )
    if contract is None:
        raise HTTPException(status_code=404, detail="No contract yet")
    if not contract.is_payment_verified:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Confirm payment received before Execution_Agent can run",
        )
    if contract.max_api_budget <= 0:
        init_budget(contract)

    result = run_execution_agent(
        contract=contract,
        lead=lead,
        task_prompt=payload.task_prompt,
        run_qa=payload.run_qa,
    )
    db.commit()
    contract = db.scalar(
        select(Contract)
        .where(Contract.id == contract.id)
        .options(selectinload(Contract.deliverables))
    )
    qa = None
    if result.qa is not None:
        qa = QAPublic(
            passed=result.qa.passed,
            completeness_pct=result.qa.completeness_pct,
            issues=sanitize_output(result.qa.issues),
            authorize_emergency_extension=result.qa.authorize_emergency_extension,
            summary=sanitize_output(result.qa.summary),
            sast_passed=result.qa.sast_passed,
            sast_log=sanitize_output(result.qa.sast_log),
            ready_for_delivery=result.qa.ready_for_delivery,
        )
    return ExecutionResponse(
        draft=sanitize_output(result.draft),
        model_used=result.model_used,
        cost_this_run=result.cost_this_run,
        cumulative_api_cost=result.cumulative_api_cost,
        max_api_budget=result.max_api_budget,
        budget_state=result.budget_state,
        effort_level=contract.effort_level,
        qa=qa,
        paused=result.paused,
        message=sanitize_output(result.message),
        contract=ContractPublic.model_validate(contract),
        sast_passed=result.sast_passed,
        ready_for_delivery=result.ready_for_delivery,
    )


@router.post("/leads/{lead_id}/authorize-budget-extension", response_model=ContractPublic)
def authorize_budget_extension(
    lead_id: UUID,
    payload: BudgetExtendRequest,
    db: DbSession,
    user: CurrentUser,
) -> ContractPublic:
    """Human: +5% (default) API budget and unpause execution."""
    lead = db.get(Lead, lead_id)
    if lead is None or lead.user_id != user.id:
        raise HTTPException(status_code=404, detail="Lead not found")
    contract = db.scalar(
        select(Contract)
        .where(Contract.lead_id == lead_id)
        .options(selectinload(Contract.deliverables))
    )
    if contract is None:
        raise HTTPException(status_code=404, detail="No contract yet")
    if not contract.is_payment_verified:
        raise HTTPException(status_code=423, detail="Payment not verified")

    ProfitGuard(contract, lead).authorize_extension(extra_ratio=payload.extra_ratio)
    db.commit()
    db.refresh(contract)
    return ContractPublic.model_validate(contract)
