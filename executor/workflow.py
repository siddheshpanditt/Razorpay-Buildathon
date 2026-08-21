"""
Bounded workflow executor.
Runs one case through: persist → rules → dispatch → simulate outcome → audit.
"""
import random
from datetime import datetime, timezone

from config import get
from data.db import get_conn
from data.models import Case, DiagnosisResult, CaseStatus
from rules_engine.rules import run_rules, all_passed
from executor.channels import send_email, send_sms, send_webhook, escalate_to_human
from interventions.templates import get_template
from audit.writer import (
    log_detection, log_diagnosis, log_rule_checks,
    log_execution, log_outcome,
)


def _persist_case(case: Case) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO cases "
        "(case_id, leak_type, event_id, customer_id, amount, currency, status, created_at) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (
            case.case_id, case.leak_type, case.event_id,
            case.customer_id, case.amount, case.currency,
            case.status, case.created_at.isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def _close_case(case_id: str, status: CaseStatus) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE cases SET status=?, closed_at=? WHERE case_id=?",
        (status, datetime.now(timezone.utc).isoformat(), case_id),
    )
    conn.commit()
    conn.close()


def _simulate_recovery(intervention: str) -> bool:
    rates: dict = get("RECOVERY_RATES", {})
    rate = rates.get(intervention, 0.0)
    return random.random() < rate


def _dispatch(case: Case, intervention: str) -> str:
    """Send via the right channel stub. Returns channel name for audit."""
    channel, template, message = get_template(intervention)

    if intervention == "suppress":
        return "none"

    if intervention == "escalate_human" or case.raw_event.get("requires_human_escalation"):
        escalate_to_human(case.case_id, case.customer_id, reason=f"intervention={intervention}")
        return "human_queue"

    if channel == "email":
        send_email(case.case_id, case.customer_id, template, {"message": message})
    elif channel == "sms":
        send_sms(case.case_id, case.customer_id, message)
    elif channel == "webhook":
        send_webhook(case.case_id, "recovery_action", {"template": template, "message": message})

    return channel


# ── public entry point ────────────────────────────────────────────────────────

def persist_case(case: Case) -> None:
    """Public wrapper used by dry-run path in run_batch.py."""
    _persist_case(case)


def execute(case: Case, diagnosis: DiagnosisResult,
            suppress_list: set[str] | None = None) -> CaseStatus:
    """
    Full pipeline for one case. Returns the final CaseStatus.
    Always writes a complete audit trail regardless of outcome.
    """
    suppress_list = suppress_list or set()

    # 1. Persist case + log detection
    _persist_case(case)
    log_detection(case)

    # 2. Log diagnosis (corrected flag already set by diagnosis.engine)
    log_diagnosis(case, diagnosis)

    # 3. Rules engine — evaluate all 7, log every result
    rule_results = run_rules(
        case, diagnosis,
        attempts_so_far=0,       # batch run: first attempt per case
        last_attempt_at=None,
        suppress_list=suppress_list,
    )
    log_rule_checks(case, rule_results)

    # 4. Hard stop if any rule failed
    if not all_passed(rule_results):
        failed_rules = [r.rule_name for r in rule_results if not r.passed]
        log_outcome(case, outcome=f"suppressed blocked_by={','.join(failed_rules)}")
        _close_case(case.case_id, "suppressed")
        return "suppressed"

    # 5. Override intervention if rules engine forced escalation
    intervention = diagnosis.recommended_intervention
    if diagnosis.requires_human_escalation:
        intervention = "escalate_human"

    # 6. Dispatch
    channel = _dispatch(case, intervention)
    log_execution(case, intervention, channel)

    # 7. Simulate outcome
    if intervention in ("escalate_human", "suppress"):
        final_status: CaseStatus = "escalated" if intervention == "escalate_human" else "suppressed"
        log_outcome(case, outcome=final_status, recovered_amount=0.0)
        _close_case(case.case_id, final_status)
        return final_status

    recovered = _simulate_recovery(intervention)
    final_status = "recovered" if recovered else "open"
    recovered_amount = case.amount if recovered else 0.0
    log_outcome(case, outcome=final_status, recovered_amount=recovered_amount)
    _close_case(case.case_id, final_status)
    return final_status
