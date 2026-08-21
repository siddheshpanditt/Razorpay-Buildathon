from __future__ import annotations
from datetime import datetime, timezone
from typing import Literal, Optional
from pydantic import BaseModel, Field
import uuid


# ── Payment failure ──────────────────────────────────────────────────────────

PaymentMethod = Literal["card", "upi", "netbanking", "wallet"]

GatewayResponseCode = Literal[
    "insufficient_funds", "expired_card", "issuer_decline",
    "gateway_timeout", "do_not_honor", "fraud_flagged", "unknown"
]

PaymentRootCause = Literal[
    "insufficient_funds", "expired_card", "issuer_decline",
    "gateway_timeout", "fraud_flagged", "unknown"
]

PaymentIntervention = Literal[
    "retry_now", "retry_scheduled", "request_payment_update",
    "offer_alternate_method", "escalate_human", "suppress"
]


class PaymentFailureEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    customer_id: str
    timestamp: datetime
    amount: float
    currency: str = "INR"
    payment_method: PaymentMethod
    gateway_response_code: GatewayResponseCode
    attempt_number: int = 1
    is_subscription_renewal: bool = False
    customer_contact_opt_in: bool = True
    do_not_contact: bool = False


# ── Checkout abandonment ─────────────────────────────────────────────────────

StageReached = Literal["cart", "shipping_info", "payment_info", "otp_verification"]
DeviceType = Literal["mobile", "desktop"]

AbandonmentRootCause = Literal[
    "price_hesitation", "otp_friction", "payment_method_missing",
    "comparison_shopping", "technical_error", "unknown"
]

AbandonmentIntervention = Literal[
    "reminder_nudge", "discount_offer", "simplify_checkout_flag",
    "escalate_human", "suppress"
]


class CheckoutAbandonmentEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    customer_id: str
    timestamp: datetime
    cart_value: float
    currency: str = "INR"
    stage_reached: StageReached
    device_type: DeviceType
    time_since_last_activity_minutes: int
    is_repeat_customer: bool = False
    customer_contact_opt_in: bool = True
    do_not_contact: bool = False


# ── Shared pipeline contracts ────────────────────────────────────────────────

LeakType = Literal["payment_failure", "checkout_abandonment"]
CaseStatus = Literal["open", "recovered", "suppressed", "escalated"]


class Case(BaseModel):
    case_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    leak_type: LeakType
    event_id: str
    customer_id: str
    amount: float          # cart_value for abandonment, amount for payment failure
    currency: str = "INR"
    status: CaseStatus = "open"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: Optional[datetime] = None
    # raw event payload kept in memory for diagnosis; not persisted in cases table
    raw_event: dict = Field(default={}, exclude=True)


class DiagnosisResult(BaseModel):
    case_id: str
    leak_type: LeakType
    root_cause: str
    confidence: float
    recommended_intervention: str
    reasoning: str
    requires_human_escalation: bool
    diagnosis_corrected: bool = False  # True when LLM output failed enum validation
