"""
Calls Claude with a strict JSON schema prompt.
Returns a validated DiagnosisResult — never free text.
"""
import json
import os
from datetime import datetime, timezone

import anthropic
from dotenv import load_dotenv

from data.db import get_conn
from data.models import (
    Case, DiagnosisResult,
    PaymentRootCause, PaymentIntervention,
    AbandonmentRootCause, AbandonmentIntervention,
)

load_dotenv()

_VALID: dict[str, tuple[set, set]] = {
    "payment_failure": (
        set(PaymentRootCause.__args__),
        set(PaymentIntervention.__args__),
    ),
    "checkout_abandonment": (
        set(AbandonmentRootCause.__args__),
        set(AbandonmentIntervention.__args__),
    ),
}

_SYSTEM = """You are a revenue-recovery diagnosis engine.
Given a payment or checkout event, return ONLY a JSON object — no prose, no markdown.
The JSON must match this exact schema:
{
  "root_cause": "<value from the allowed enum>",
  "confidence": <float 0.0-1.0>,
  "recommended_intervention": "<value from the allowed enum>",
  "reasoning": "<one sentence, audit-only, never shown to customer>",
  "requires_human_escalation": <true|false>
}"""


def _build_prompt(case: Case) -> str:
    valid_causes, valid_interventions = _valid_enums(case.leak_type)
    return (
        f"leak_type: {case.leak_type}\n"
        f"event: {json.dumps(case.raw_event, default=str)}\n\n"
        f"allowed root_cause values: {sorted(valid_causes)}\n"
        f"allowed recommended_intervention values: {sorted(valid_interventions)}\n"
    )


def _valid_enums(leak_type: str) -> tuple[set, set]:
    return _VALID[leak_type]


def _validate(raw: dict, case: Case) -> DiagnosisResult:
    valid_causes, valid_interventions = _valid_enums(case.leak_type)
    corrected = False

    root_cause = raw.get("root_cause", "unknown")
    if root_cause not in valid_causes:
        root_cause = "unknown"
        corrected = True

    intervention = raw.get("recommended_intervention", "suppress")
    if intervention not in valid_interventions:
        intervention = "suppress"
        corrected = True

    confidence = float(raw.get("confidence", 0.0))
    if not (0.0 <= confidence <= 1.0):
        confidence = max(0.0, min(1.0, confidence))
        corrected = True

    # Also flag when raw was empty (JSON parse failed entirely)
    if not raw:
        corrected = True

    return DiagnosisResult(
        case_id=case.case_id,
        leak_type=case.leak_type,
        root_cause=root_cause,
        confidence=confidence,
        recommended_intervention=intervention,
        reasoning=str(raw.get("reasoning", ""))[:500],
        requires_human_escalation=bool(raw.get("requires_human_escalation", False)),
        diagnosis_corrected=corrected,
    )


def diagnose(case: Case) -> DiagnosisResult:
    model = os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    message = client.messages.create(
        model=model,
        max_tokens=256,
        system=_SYSTEM,
        messages=[{"role": "user", "content": _build_prompt(case)}],
    )

    raw_text = message.content[0].text.strip()

    # Strip markdown code fences if the model wraps output anyway
    if raw_text.startswith("```"):
        raw_text = raw_text.split("```")[1]
        if raw_text.startswith("json"):
            raw_text = raw_text[4:]

    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError:
        # Fallback: safe defaults so the pipeline never crashes on a bad LLM response
        raw = {}

    return _validate(raw, case)


def persist_diagnosis(result: DiagnosisResult) -> None:
    conn = get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO diagnosis_results
           (case_id, leak_type, root_cause, confidence,
            recommended_intervention, reasoning,
            requires_human_escalation, diagnosis_corrected, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            result.case_id, result.leak_type, result.root_cause,
            result.confidence, result.recommended_intervention,
            result.reasoning, int(result.requires_human_escalation),
            int(result.diagnosis_corrected),
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    conn.close()
# ── Mock diagnosis (no API key needed) ─────────────────────────────────────

_PAYMENT_CAUSE_MAP: dict[str, tuple[str, str]] = {
    # gateway_response_code -> (root_cause, recommended_intervention)
    "insufficient_funds": ("insufficient_funds", "retry_scheduled"),
    "expired_card": ("expired_card", "request_payment_update"),
    "issuer_decline": ("issuer_decline", "offer_alternate_method"),
    "gateway_timeout": ("gateway_timeout", "retry_now"),
    "do_not_honor": ("issuer_decline", "offer_alternate_method"),
    "fraud_flagged": ("fraud_flagged", "escalate_human"),
    "unknown": ("unknown", "suppress"),
}

_ABANDONMENT_CAUSE_MAP: dict[str, tuple[str, str]] = {
    # stage_reached -> (root_cause, recommended_intervention)
    "cart": ("price_hesitation", "discount_offer"),
    "shipping_info": ("comparison_shopping", "reminder_nudge"),
    "payment_info": ("payment_method_missing", "reminder_nudge"),
    "otp_verification": ("otp_friction", "simplify_checkout_flag"),
}


def diagnose_mock(case: Case) -> DiagnosisResult:
    """
    Deterministic-but-varied diagnosis, no Claude API call.
    """
    if case.leak_type == "payment_failure":
        code = case.raw_event.get("gateway_response_code", "unknown")
        root_cause, intervention = _PAYMENT_CAUSE_MAP.get(code, ("unknown", "suppress"))
        escalate = root_cause == "fraud_flagged"
        reasoning = f"mock: gateway_response_code={code}"
    else:
        stage = case.raw_event.get("stage_reached", "cart")
        root_cause, intervention = _ABANDONMENT_CAUSE_MAP.get(stage, ("price_hesitation", "reminder_nudge"))
        escalate = False
        reasoning = f"mock: stage_reached={stage}"

    return DiagnosisResult(
        case_id=case.case_id,
        leak_type=case.leak_type,
        root_cause=root_cause,
        confidence=0.75,
        recommended_intervention=intervention,
        reasoning=reasoning,
        requires_human_escalation=escalate,
        diagnosis_corrected=False,
    )