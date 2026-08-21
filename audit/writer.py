"""
Audit log writer and query helpers.
Every write uses structured key=value detail strings for programmatic filtering.
"""
from datetime import datetime, timezone
from typing import Optional

from data.db import get_conn
from data.models import Case, DiagnosisResult
from rules_engine.rules import RuleResult


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(case_id: str, stage: str, result: str,
           detail: str, rule_name: Optional[str] = None) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO audit_log (case_id, timestamp, stage, rule_name, result, detail) "
        "VALUES (?,?,?,?,?,?)",
        (case_id, _now(), stage, rule_name, result, detail),
    )
    conn.commit()
    conn.close()


# ── one writer per pipeline stage ────────────────────────────────────────────

def log_detection(case: Case) -> None:
    _write(
        case.case_id, stage="detection", result="info",
        detail=f"leak_type={case.leak_type} event_id={case.event_id} amount={case.amount}",
    )


def log_diagnosis(case: Case, diagnosis: DiagnosisResult) -> None:
    if diagnosis.diagnosis_corrected:
        _write(
            case.case_id, stage="diagnosis", result="warn",
            detail=(
                f"corrected=true root_cause={diagnosis.root_cause} "
                f"intervention={diagnosis.recommended_intervention} "
                f"confidence={diagnosis.confidence:.2f}"
            ),
        )
    else:
        _write(
            case.case_id, stage="diagnosis", result="pass",
            detail=(
                f"corrected=false root_cause={diagnosis.root_cause} "
                f"intervention={diagnosis.recommended_intervention} "
                f"confidence={diagnosis.confidence:.2f} "
                f"requires_escalation={diagnosis.requires_human_escalation}"
            ),
        )


def log_rule_checks(case: Case, results: list[RuleResult]) -> None:
    for r in results:
        _write(
            case.case_id,
            stage="rule_check",
            result="pass" if r.passed else "fail",
            rule_name=r.rule_name,
            detail=r.detail,
        )


def log_execution(case: Case, intervention: str, channel: str) -> None:
    _write(
        case.case_id, stage="execution", result="info",
        detail=f"intervention={intervention} channel={channel}",
    )


def log_outcome(case: Case, outcome: str, recovered_amount: float = 0.0) -> None:
    _write(
        case.case_id, stage="outcome", result="info",
        detail=f"outcome={outcome} recovered_amount={recovered_amount}",
    )


# ── query helpers ─────────────────────────────────────────────────────────────

def get_case_trail(case_id: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM audit_log WHERE case_id=? ORDER BY id", (case_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_corrected_diagnoses() -> list[dict]:
    """All cases where LLM output was invalid and fell back to unknown/suppress."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM audit_log WHERE stage='diagnosis' AND result='warn' ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_rules_engine_escalations() -> list[dict]:
    """Cases where the rules engine forced escalation (not the LLM)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM audit_log "
        "WHERE stage='rule_check' AND rule_name='high_value_escalation' "
        "AND detail LIKE 'forced_by=rules_engine%' ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_blocked_cases() -> list[dict]:
    """Cases blocked by any hard-stop rule."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT case_id, rule_name, detail FROM audit_log "
        "WHERE stage='rule_check' AND result='fail' ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
