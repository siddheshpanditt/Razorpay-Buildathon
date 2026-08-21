"""
Rules engine tests — no LLM, no network, no DB required.
Run: pytest tests/test_rules_engine.py -v
"""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from data.models import Case, DiagnosisResult
from rules_engine.rules import (
    check_do_not_contact,
    check_opt_in,
    check_max_attempts,
    check_cooldown,
    check_contact_window,
    check_high_value_escalation,
    check_suppress_list,
    run_rules,
    all_passed,
)


# ── fixtures ─────────────────────────────────────────────────────────────────

def make_case(amount=1000.0, dnc=False, opt_in=True, **kwargs) -> Case:
    return Case(
        leak_type="payment_failure",
        event_id="evt-test-1",
        customer_id="cust-test-1",
        amount=amount,
        raw_event={"do_not_contact": dnc, "customer_contact_opt_in": opt_in, **kwargs},
    )


def make_diagnosis(case: Case, requires_escalation=False) -> DiagnosisResult:
    return DiagnosisResult(
        case_id=case.case_id,
        leak_type=case.leak_type,
        root_cause="issuer_decline",
        confidence=0.85,
        recommended_intervention="retry_now",
        reasoning="test",
        requires_human_escalation=requires_escalation,
    )


# ── do_not_contact ────────────────────────────────────────────────────────────

def test_dnc_blocks_when_set():
    case = make_case(dnc=True)
    result = check_do_not_contact(case)
    assert not result.passed
    assert result.rule_name == "do_not_contact"


def test_dnc_passes_when_clear():
    case = make_case(dnc=False)
    assert check_do_not_contact(case).passed


# ── opt_in ────────────────────────────────────────────────────────────────────

def test_opt_in_blocks_when_false():
    case = make_case(opt_in=False)
    assert not check_opt_in(case).passed


def test_opt_in_passes_when_true():
    case = make_case(opt_in=True)
    assert check_opt_in(case).passed


# ── max_attempts ──────────────────────────────────────────────────────────────

def test_max_attempts_blocks_at_limit():
    case = make_case()
    # default limit is 3; at 3 attempts it should block
    result = check_max_attempts(case, attempts_so_far=3)
    assert not result.passed


def test_max_attempts_passes_below_limit():
    case = make_case()
    assert check_max_attempts(case, attempts_so_far=2).passed


def test_max_attempts_passes_at_zero():
    case = make_case()
    assert check_max_attempts(case, attempts_so_far=0).passed


def test_max_attempts_respects_config_override():
    case = make_case()
    with patch("rules_engine.rules.get", return_value=5):
        assert check_max_attempts(case, attempts_so_far=4).passed
        assert not check_max_attempts(case, attempts_so_far=5).passed


# ── cooldown ──────────────────────────────────────────────────────────────────

def test_cooldown_passes_with_no_prior_attempt():
    case = make_case()
    assert check_cooldown(case, last_attempt_at=None).passed


def test_cooldown_blocks_within_window():
    case = make_case()
    recent = datetime.now(timezone.utc) - timedelta(hours=2)
    assert not check_cooldown(case, last_attempt_at=recent).passed


def test_cooldown_passes_after_window():
    case = make_case()
    old = datetime.now(timezone.utc) - timedelta(hours=5)
    assert check_cooldown(case, last_attempt_at=old).passed


def test_cooldown_passes_exactly_at_boundary():
    case = make_case()
    # exactly 4 hours ago should pass (elapsed >= cooldown_hours)
    boundary = datetime.now(timezone.utc) - timedelta(hours=4, seconds=1)
    assert check_cooldown(case, last_attempt_at=boundary).passed


def test_cooldown_handles_naive_datetime():
    """Naive datetimes (no tzinfo) should be treated as UTC without crashing."""
    case = make_case()
    naive = datetime.now() - timedelta(hours=10)  # intentionally naive (no tzinfo)
    assert check_cooldown(case, last_attempt_at=naive).passed


# ── contact_window ────────────────────────────────────────────────────────────

def _ist_dt(weekday: int, hour: int) -> datetime:
    """Build a timezone-aware IST datetime with the given weekday and hour."""
    import zoneinfo
    IST = zoneinfo.ZoneInfo("Asia/Kolkata")
    # Find next occurrence of the target weekday from a known Monday
    base = datetime(2024, 1, 1, hour, 0, 0, tzinfo=IST)  # 2024-01-01 is a Monday
    days_ahead = (weekday - base.weekday()) % 7
    return base + timedelta(days=days_ahead)


def test_contact_window_passes_weekday_business_hours():
    ist_dt = _ist_dt(weekday=0, hour=10)  # Monday 10 AM IST
    with patch("rules_engine.rules.datetime") as mock_dt:
        mock_dt.now.return_value = ist_dt
        assert check_contact_window().passed


def test_contact_window_blocks_before_start():
    ist_dt = _ist_dt(weekday=1, hour=8)  # Tuesday 8 AM IST
    with patch("rules_engine.rules.datetime") as mock_dt:
        mock_dt.now.return_value = ist_dt
        assert not check_contact_window().passed


def test_contact_window_blocks_after_end():
    ist_dt = _ist_dt(weekday=2, hour=22)  # Wednesday 10 PM IST
    with patch("rules_engine.rules.datetime") as mock_dt:
        mock_dt.now.return_value = ist_dt
        assert not check_contact_window().passed


def test_contact_window_blocks_on_sunday():
    ist_dt = _ist_dt(weekday=6, hour=12)  # Sunday noon IST
    with patch("rules_engine.rules.datetime") as mock_dt:
        mock_dt.now.return_value = ist_dt
        assert not check_contact_window().passed


def test_contact_window_passes_on_saturday():
    ist_dt = _ist_dt(weekday=5, hour=14)  # Saturday 2 PM IST
    with patch("rules_engine.rules.datetime") as mock_dt:
        mock_dt.now.return_value = ist_dt
        assert check_contact_window().passed


# ── high_value_escalation ─────────────────────────────────────────────────────

def test_high_value_upgrades_diagnosis_flag():
    case = make_case(amount=75000.0)
    diagnosis = make_diagnosis(case, requires_escalation=False)
    result = check_high_value_escalation(case, diagnosis)
    assert result.passed                          # never blocks
    assert diagnosis.requires_human_escalation    # flag mutated


def test_high_value_does_not_downgrade_existing_flag():
    case = make_case(amount=100.0)
    diagnosis = make_diagnosis(case, requires_escalation=True)
    check_high_value_escalation(case, diagnosis)
    assert diagnosis.requires_human_escalation    # unchanged


def test_below_threshold_leaves_flag_false():
    case = make_case(amount=1000.0)
    diagnosis = make_diagnosis(case, requires_escalation=False)
    check_high_value_escalation(case, diagnosis)
    assert not diagnosis.requires_human_escalation


# ── suppress_list ─────────────────────────────────────────────────────────────

def test_suppress_list_blocks_by_case_id():
    case = make_case()
    result = check_suppress_list(case, suppress_list={case.case_id})
    assert not result.passed


def test_suppress_list_blocks_by_event_id():
    case = make_case()
    result = check_suppress_list(case, suppress_list={case.event_id})
    assert not result.passed


def test_suppress_list_passes_when_not_listed():
    case = make_case()
    assert check_suppress_list(case, suppress_list={"other-id"}).passed


def test_suppress_list_passes_with_empty_list():
    case = make_case()
    assert check_suppress_list(case, suppress_list=set()).passed


# ── run_rules integration ─────────────────────────────────────────────────────

def test_run_rules_all_pass_clean_case():
    case = make_case()
    diagnosis = make_diagnosis(case)
    ist_dt = _ist_dt(weekday=0, hour=10)
    with patch("rules_engine.rules.datetime") as mock_dt:
        mock_dt.now.return_value = ist_dt
        results = run_rules(case, diagnosis, attempts_so_far=0, last_attempt_at=None)
    assert all_passed(results)
    assert len(results) == 7


def test_run_rules_fails_on_dnc():
    case = make_case(dnc=True)
    diagnosis = make_diagnosis(case)
    results = run_rules(case, diagnosis)
    assert not all_passed(results)
    failed = [r for r in results if not r.passed]
    assert any(r.rule_name == "do_not_contact" for r in failed)


def test_run_rules_fails_on_max_attempts():
    case = make_case()
    diagnosis = make_diagnosis(case)
    results = run_rules(case, diagnosis, attempts_so_far=3)
    assert not all_passed(results)
    assert any(r.rule_name == "max_attempts" for r in results if not r.passed)


def test_run_rules_returns_all_results_even_on_early_fail():
    """All 7 rules must always be evaluated and returned (for full audit trail)."""
    case = make_case(dnc=True)
    diagnosis = make_diagnosis(case)
    results = run_rules(case, diagnosis)
    assert len(results) == 7
