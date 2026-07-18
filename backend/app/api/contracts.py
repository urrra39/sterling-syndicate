from __future__ import annotations

"""Contract & deliverable tracker — payment kill switch enforced."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession, PaymentApprover
from app.models.lead import Lead, PipelineStatus
from app.models.proposal import Contract, Deliverable
from app.schemas.crm import (
    ContractCreate,
    ContractPublic,
    DeliverablePublic,
    DeliverableStatusUpdate,
)
from app.services.payment_guard import (
    assert_payment_cleared,
    confirm_payment_received,
    lock_for_payment_verification,
)
from app.services.payment_stepup import verify_totp, verify_webhook_signature

router = APIRouter()


class ContractCreateExt(ContractCreate):
    client_display_name: Optional[str] = Field(default=None, max_length=200)


class PaymentClaimRequest(BaseModel):
    client_display_name: Optional[str] = Field(default=None, max_length=200)
    amount: Optional[float] = Field(default=None, gt=0, le=10_000_000)


class ConfirmPaymentRequest(BaseModel):
    """Optional step-up MFA proof for releasing the payment kill switch."""

    mfa_code: Optional[str] = Field(default=None, max_length=12)


@router.post(
    "/leads/{lead_id}/contract",
    response_model=ContractPublic,
    status_code=status.HTTP_201_CREATED,
)
def create_contract(
    lead_id: UUID,
    payload: ContractCreateExt,
    db: DbSession,
    user: CurrentUser,
) -> ContractPublic:
    """Create contract and immediately lock until payment is human-verified."""
    lead = db.get(Lead, lead_id)
    if lead is None or lead.user_id != user.id:
        raise HTTPException(status_code=404, detail="Lead not found")
    existing = db.scalar(select(Contract).where(Contract.lead_id == lead_id))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Contract already exists for this lead")

    client_name = (payload.client_display_name or lead.title or "Client").strip()[:200]
    contract = Contract(
        lead_id=lead.id,
        agreed_scope=payload.agreed_scope.strip(),
        agreed_price=payload.agreed_price,
        currency=payload.currency.upper()[:8],
        deadline=payload.deadline,
        status="pending_payment_verification",
        is_payment_verified=False,
        client_display_name=client_name,
    )
    db.add(contract)
    db.flush()
    for d in payload.deliverables:
        db.add(
            Deliverable(
                contract_id=contract.id,
                description=d.description.strip(),
                status="pending",  # never start work pre-verification
                checklist=[c.strip() for c in d.checklist if c.strip()][:50],
            )
        )
    lock_for_payment_verification(
        db,
        lead=lead,
        contract=contract,
        client_name=client_name,
        amount=payload.agreed_price,
        send_alert=True,
    )
    db.commit()
    contract = db.scalar(
        select(Contract)
        .where(Contract.id == contract.id)
        .options(selectinload(Contract.deliverables))
    )
    return ContractPublic.model_validate(contract)


@router.get("/leads/{lead_id}/contract", response_model=ContractPublic)
def get_contract(lead_id: UUID, db: DbSession, user: CurrentUser) -> ContractPublic:
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
    return ContractPublic.model_validate(contract)


@router.post("/leads/{lead_id}/payment-claimed", response_model=ContractPublic)
def claim_payment(
    lead_id: UUID,
    payload: PaymentClaimRequest,
    db: DbSession,
    user: CurrentUser,
) -> ContractPublic:
    """Client claims payment / agreement reached → freeze all agent work + alert."""
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
    if contract.is_payment_verified:
        return ContractPublic.model_validate(contract)

    name = payload.client_display_name or contract.client_display_name or lead.title or "Client"
    lock_for_payment_verification(
        db,
        lead=lead,
        contract=contract,
        client_name=name,
        amount=payload.amount or contract.agreed_price,
        send_alert=True,
    )
    db.commit()
    db.refresh(contract)
    return ContractPublic.model_validate(contract)


@router.post("/leads/{lead_id}/confirm-payment", response_model=ContractPublic)
def confirm_payment(
    lead_id: UUID,
    payload: ConfirmPaymentRequest,
    db: DbSession,
    user: PaymentApprover,
) -> ContractPublic:
    """Release the payment kill switch after funds are human-verified.

    RBAC: restricted to owner/approver roles (``PaymentApprover``), not any
    logged-in tenant. When ``PAYMENT_STEPUP_REQUIRED`` is enabled, the caller
    must ALSO present a valid step-up TOTP code — so a mere session cookie is
    not enough to unlock delivery work and start agent spend.
    """
    if settings.payment_stepup_required:
        if not verify_totp(payload.mfa_code or ""):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Step-up MFA required: provide a valid authenticator code to confirm payment.",
            )

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

    confirm_payment_received(db, lead=lead, contract=contract)
    db.commit()
    db.refresh(contract)
    return ContractPublic.model_validate(contract)


@router.post("/leads/{lead_id}/payment-webhook", response_model=ContractPublic)
async def payment_webhook(
    lead_id: UUID,
    request: Request,
    db: DbSession,
) -> ContractPublic:
    """Signed payment-provider webhook that clears a contract without a login.

    The provider signs the raw request body with HMAC-SHA256 using
    ``PAYMENT_WEBHOOK_SECRET`` and sends it in ``X-Payment-Signature``. This is
    the trusted, backend-validated path for marking funds received — as opposed
    to a simple tenant-owner login. Verification is constant-time.
    """
    secret = settings.payment_webhook_secret
    if not secret:
        raise HTTPException(status_code=404, detail="Payment webhook is not configured")

    raw = await request.body()
    signature = request.headers.get("x-payment-signature", "")
    if not verify_webhook_signature(raw, signature, secret=secret):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )

    lead = db.get(Lead, lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead not found")
    contract = db.scalar(
        select(Contract)
        .where(Contract.lead_id == lead_id)
        .options(selectinload(Contract.deliverables))
    )
    if contract is None:
        raise HTTPException(status_code=404, detail="No contract yet")

    confirm_payment_received(db, lead=lead, contract=contract)
    db.commit()
    db.refresh(contract)
    return ContractPublic.model_validate(contract)


@router.patch("/deliverables/{deliverable_id}", response_model=DeliverablePublic)
def update_deliverable(
    deliverable_id: UUID,
    payload: DeliverableStatusUpdate,
    db: DbSession,
    user: CurrentUser,
) -> DeliverablePublic:
    deliverable = db.get(Deliverable, deliverable_id)
    if deliverable is None:
        raise HTTPException(status_code=404, detail="Deliverable not found")
    contract = db.get(Contract, deliverable.contract_id)
    lead = db.get(Lead, contract.lead_id) if contract else None
    if lead is None or lead.user_id != user.id:
        raise HTTPException(status_code=404, detail="Deliverable not found")

    # Absolute blocker: no delivery progress until payment verified
    assert_payment_cleared(db, lead.id)

    # Also block marking delivered while unverified (belt + suspenders)
    if payload.status in {"in_progress", "delivered"} and not contract.is_payment_verified:
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Cannot advance deliverables until payment is confirmed.",
        )

    deliverable.status = payload.status
    if payload.checklist is not None:
        deliverable.checklist = [c.strip() for c in payload.checklist if c.strip()][:50]

    all_d = db.scalars(
        select(Deliverable).where(Deliverable.contract_id == contract.id)
    ).all()
    # PAID is terminal — a later deliverable edit must not regress a paid deal
    # back to DELIVERED/IN_PROGRESS.
    if lead.pipeline_status != PipelineStatus.PAID.value:
        if all(d.status == "delivered" for d in all_d):
            lead.pipeline_status = PipelineStatus.DELIVERED.value
            contract.status = "completed"
        elif any(d.status == "in_progress" for d in all_d) or any(
            d.status == "delivered" for d in all_d
        ):
            lead.pipeline_status = PipelineStatus.IN_PROGRESS.value

    db.commit()
    db.refresh(deliverable)
    return DeliverablePublic.model_validate(deliverable)


@router.post("/leads/{lead_id}/mark-paid", response_model=ContractPublic)
def mark_paid(lead_id: UUID, db: DbSession, user: CurrentUser) -> ContractPublic:
    """Final paid state — only after payment was verified."""
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
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Confirm Payment Received before marking the deal paid.",
        )
    lead.pipeline_status = PipelineStatus.PAID.value
    contract.status = "completed"
    db.commit()
    db.refresh(contract)
    return ContractPublic.model_validate(contract)
