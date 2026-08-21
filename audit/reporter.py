"""
Queries the audit log and cases table to produce batch summary stats.
All numbers derived from DB — no in-memory state required.
"""
from data.db import get_conn


def _rows(sql: str, params: tuple = ()) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def revenue_summary() -> dict:
    """Total at-risk, total recovered, overall recovery rate."""
    row = _rows("""
        SELECT
            COUNT(*)                                        AS total_cases,
            COALESCE(SUM(amount), 0)                        AS total_at_risk,
            COALESCE(SUM(CASE WHEN status='recovered'
                         THEN amount ELSE 0 END), 0)        AS total_recovered,
            COALESCE(SUM(CASE WHEN status='escalated'
                         THEN amount ELSE 0 END), 0)        AS total_escalated,
            COALESCE(SUM(CASE WHEN status='suppressed'
                         THEN amount ELSE 0 END), 0)        AS total_suppressed
        FROM cases
    """)[0]
    at_risk = row["total_at_risk"]
    recovered = row["total_recovered"]
    row["recovery_rate"] = round(recovered / at_risk, 4) if at_risk else 0.0
    return row


def breakdown_by_leak_type() -> list[dict]:
    rows = _rows("""
        SELECT
            c.leak_type,
            COUNT(*)                                        AS cases,
            COALESCE(SUM(c.amount), 0)                      AS at_risk,
            COALESCE(SUM(CASE WHEN c.status='recovered'
                         THEN c.amount ELSE 0 END), 0)      AS recovered,
            ROUND(COALESCE(SUM(CASE WHEN c.status='recovered'
                         THEN c.amount ELSE 0 END), 0)
                  / MAX(SUM(c.amount), 1), 4)               AS recovery_rate
        FROM cases c
        GROUP BY c.leak_type
    """)
    return rows


def breakdown_by_root_cause() -> list[dict]:
    rows = _rows("""
        SELECT
            d.leak_type,
            d.root_cause,
            COUNT(*)                                        AS cases,
            COALESCE(SUM(c.amount), 0)                      AS at_risk,
            COALESCE(SUM(CASE WHEN c.status='recovered'
                         THEN c.amount ELSE 0 END), 0)      AS recovered,
            ROUND(COALESCE(SUM(CASE WHEN c.status='recovered'
                         THEN c.amount ELSE 0 END), 0)
                  / MAX(SUM(c.amount), 1), 4)               AS recovery_rate
        FROM cases c
        JOIN diagnosis_results d ON c.case_id = d.case_id
        GROUP BY d.leak_type, d.root_cause
        ORDER BY at_risk DESC
    """)
    return rows


def audit_flags() -> dict:
    """Counts of notable audit events for the batch summary."""
    corrected = _rows(
        "SELECT COUNT(*) AS n FROM audit_log "
        "WHERE stage='diagnosis' AND result='warn'"
    )[0]["n"]
    forced_escalations = _rows(
        "SELECT COUNT(*) AS n FROM audit_log "
        "WHERE stage='rule_check' AND rule_name='high_value_escalation' "
        "AND detail LIKE 'forced_by=rules_engine%'"
    )[0]["n"]
    blocked = _rows(
        "SELECT COUNT(DISTINCT case_id) AS n FROM audit_log "
        "WHERE stage='rule_check' AND result='fail'"
    )[0]["n"]
    return {
        "llm_output_corrected": corrected,
        "rules_engine_forced_escalations": forced_escalations,
        "hard_blocked_cases": blocked,
    }


def per_case_trail() -> list[dict]:
    """Full per-case summary joined with diagnosis for the audit table."""
    return _rows("""
        SELECT
            c.case_id,
            c.leak_type,
            c.customer_id,
            c.amount,
            c.currency,
            c.status,
            c.created_at,
            d.root_cause,
            d.recommended_intervention,
            d.confidence,
            d.requires_human_escalation,
            d.diagnosis_corrected
        FROM cases c
        LEFT JOIN diagnosis_results d ON c.case_id = d.case_id
        ORDER BY c.created_at DESC
    """)
