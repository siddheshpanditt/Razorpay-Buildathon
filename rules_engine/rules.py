"""
Stopping rules — plain code, no LLM dependency.
Every rule returns a RuleResult. The engine runs all rules and returns the list.
A single FAIL blocks execution.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
import zoneinfo

from config import get
from data.models import Case, DiagnosisResult

IST = zoneinfo.ZoneInfo("Asia/Kolkata")


@dataclass
class RuleResult:
    rule_name: str
    passed: bool
    detail: str


# ── individual rules ─────────────────────────────────────────────────────────

def check_do_not_contact(case: Case) -> RuleResult:
    dnc = case.raw_event.get("do_not_contact", False)
    return RuleResult(
        rule_name="do_not_contact",
        passed=not dnc,
        detail="do_not_contact flag is set" if dnc else "do_not_contact clear",
    )


def check_opt_in(case: Case) -> RuleResult:
    opted_in = case.raw_event.get("customer_contact_opt_in", True)
    return RuleResult(
        rule_name="opt_in",
        passed=bool(opted_in),
        detail="customer has not opted in" if not opted_in else "opt-in confirmed",
    )


def check_max_attempts(case: Case, attempts_so_far: int) -> RuleResult:
    limit = get("MAX_ATTEMPTS_PER_CASE", 3)
    passed = attempts_so_far < limit
    return RuleResult(
        rule_name="max_attempts",
        passed=passed,
        detail=f"attempts={attempts_so_far} limit={limit}",
    )


def check_cooldown(case: Case, last_attempt_at: Optional[datetime]) -> RuleResult:
    if last_attempt_at is None:
        return RuleResult(rule_name="cooldown", passed=True, detail="no prior attempt")
    cooldown_hours = get("COOLDOWN_HOURS", 4)
    now = datetime.now(timezone.utc)
    # make last_attempt_at tz-aware if it isn't
    if last_attempt_at.tzinfo is None:
        last_attempt_at = last_attempt_at.replace(tzinfo=timezone.utc)
    elapsed_hours = (now - last_attempt_at).total_seconds() / 3600
    passed = elapsed_hours >= cooldown_hours
    return RuleResult(
        rule_name="cooldown",
        passed=passed,
        detail=f"elapsed={elapsed_hours:.1f}h required={cooldown_hours}h",
    )


def check_contact_window() -> RuleResult:
    """IST 9 AM – 9 PM, Mon–Sat only."""
    now_ist = datetime.now(IST)
    start = get("CONTACT_WINDOW_START_HOUR", 9)
    end = get("CONTACT_WINDOW_END_HOUR", 21)
    allowed_days = set(get("CONTACT_WINDOW_DAYS", [0, 1, 2, 3, 4, 5]))
    in_hours = start <= now_ist.hour < end
    in_days = now_ist.weekday() in allowed_days
    passed = in_hours and in_days
    return RuleResult(
        rule_name="contact_window",
        passed=passed,
        detail=(
            f"IST {now_ist.strftime('%a %H:%M')} — "
            f"{'in' if passed else 'outside'} window "
            f"({start:02d}:00–{end:02d}:00 Mon–Sat)"
        ),
    )


def check_high_value_escalation(case: Case, diagnosis: DiagnosisResult) -> RuleResult:
    threshold = get("HIGH_VALUE_ESCALATION_THRESHOLD_INR", 50000)
    exceeds = case.amount > threshold
    llm_had_already_escalated = diagnosis.requires_human_escalation

    if exceeds and not llm_had_already_escalated:
        diagnosis.requires_human_escalation = True
        detail = (
            f"forced_by=rules_engine amount={case.amount} threshold={threshold}"
        )
    elif exceeds and llm_had_already_escalated:
        detail = (
            f"forced_by=llm amount={case.amount} threshold={threshold} rules_engine=confirms"
        )
    else:
        detail = f"escalation=none amount={case.amount} threshold={threshold}"

    return RuleResult(
        rule_name="high_value_escalation",
        passed=True,  # never blocks — only upgrades
        detail=detail,
    )


def check_suppress_list(case: Case, suppress_list: set[str]) -> RuleResult:
    blocked = case.case_id in suppress_list or case.event_id in suppress_list
    return RuleResult(
        rule_name="suppress_list",
        passed=not blocked,
        detail="case on suppress/legal-hold list" if blocked else "not on suppress list",
    )


# ── engine entry point ───────────────────────────────────────────────────────

def run_rules(
    case: Case,
    diagnosis: DiagnosisResult,
    attempts_so_far: int = 0,
    last_attempt_at: Optional[datetime] = None,
    suppress_list: Optional[set[str]] = None,
) -> list[RuleResult]:
    """
    Run all rules in priority order.
    Returns the full list — callers inspect .passed on each entry.
    Hard-block rules (DNC, opt-in, max attempts, cooldown, suppress list) are
    checked first; soft rules (high-value escalation, contact window) follow.
    """
    suppress_list = suppress_list or set()
    results = [
        check_do_not_contact(case),
        check_opt_in(case),
        check_suppress_list(case, suppress_list),
        check_max_attempts(case, attempts_so_far),
        check_cooldown(case, last_attempt_at),
        check_contact_window(),
        check_high_value_escalation(case, diagnosis),
    ]
    return results


def all_passed(results: list[RuleResult]) -> bool:
    return all(r.passed for r in results)
