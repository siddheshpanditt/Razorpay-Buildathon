"""
CLI batch runner.
Usage:
    python run_batch.py                        # process all unprocessed events
    python run_batch.py --limit 20             # cap at 20 events
    python run_batch.py --dry-run              # detect + diagnose only, no execution
    python run_batch.py --suppress id1,id2     # add case/event IDs to suppress list
    python run_batch.py --mock-diagnosis        # skip Claude API, use rule-based mock diagnosis
"""
import argparse
import sys
from datetime import datetime, timezone

from data.init_db import init_db
from data.generate_payment_failures import generate as gen_payments
from data.generate_checkout_abandonments import generate as gen_abandonments
import detectors.payment_failure as pf_detector
import detectors.checkout_abandonment as ca_detector
from diagnosis.engine import diagnose, diagnose_mock, persist_diagnosis
from executor.workflow import execute
from audit.reporter import (
    revenue_summary, breakdown_by_leak_type,
    breakdown_by_root_cause, audit_flags,
)


# ── formatting helpers ────────────────────────────────────────────────────────

def _hr(char: str = "─", width: int = 72) -> None:
    print(char * width)


def _fmt_inr(amount: float) -> str:
    return f"₹{amount:>12,.2f}"


def _pct(rate: float) -> str:
    return f"{rate * 100:5.1f}%"


def print_summary(dry_run: bool = False) -> None:
    _hr("═")
    print("  AI REVENUE RECOVERY — BATCH SUMMARY")
    if dry_run:
        print("  ⚠  DRY RUN — no interventions executed")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    _hr("═")

    s = revenue_summary()
    print(f"\n  Total cases processed : {s['total_cases']}")
    print(f"  Revenue at risk       : {_fmt_inr(s['total_at_risk'])}")
    print(f"  Revenue recovered     : {_fmt_inr(s['total_recovered'])}")
    print(f"  Recovery rate         : {_pct(s['recovery_rate'])}")
    print(f"  Escalated             : {_fmt_inr(s['total_escalated'])}")
    print(f"  Suppressed            : {_fmt_inr(s['total_suppressed'])}")

    _hr()
    print("\n  BY LEAK TYPE\n")
    print(f"  {'Leak type':<28} {'Cases':>6} {'At risk':>14} {'Recovered':>14} {'Rate':>7}")
    _hr()
    for r in breakdown_by_leak_type():
        print(
            f"  {r['leak_type']:<28} {r['cases']:>6} "
            f"{_fmt_inr(r['at_risk'])} {_fmt_inr(r['recovered'])} "
            f"{_pct(r['recovery_rate'])}"
        )

    _hr()
    print("\n  BY ROOT CAUSE\n")
    print(f"  {'Leak type':<22} {'Root cause':<28} {'Cases':>5} {'At risk':>14} {'Rate':>7}")
    _hr()
    for r in breakdown_by_root_cause():
        print(
            f"  {r['leak_type']:<22} {r['root_cause']:<28} {r['cases']:>5} "
            f"{_fmt_inr(r['at_risk'])} {_pct(r['recovery_rate'])}"
        )

    _hr()
    print("\n  AUDIT FLAGS\n")
    flags = audit_flags()
    print(f"  LLM output corrected (invalid enum)  : {flags['llm_output_corrected']}")
    print(f"  Rules-engine-forced escalations      : {flags['rules_engine_forced_escalations']}")
    print(f"  Hard-blocked cases (DNC/opt-out/etc) : {flags['hard_blocked_cases']}")
    _hr("═")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="AI Revenue Recovery batch runner")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max events to process in this run")
    parser.add_argument("--dry-run", action="store_true",
                        help="Detect + diagnose only; skip execution")
    parser.add_argument("--generate", type=int, default=0,
                        help="Generate N synthetic events of each type before running")
    parser.add_argument("--suppress", type=str, default="",
                        help="Comma-separated case/event IDs to suppress")
    parser.add_argument("--mock-diagnosis", action="store_true",
                        help="Skip the real Claude API call, use rule-based mock diagnosis instead")
    args = parser.parse_args()

    # Ensure DB exists
    init_db()

    # Optionally seed fresh events
    if args.generate > 0:
        gen_payments(args.generate)
        gen_abandonments(args.generate)

    suppress_list = {s.strip() for s in args.suppress.split(",") if s.strip()}

    # Load all unprocessed events across both leak types
    pf_events = [(e, pf_detector.detect) for e in pf_detector.load_unprocessed_events()]
    ca_events = [(e, ca_detector.detect) for e in ca_detector.load_unprocessed_events()]
    all_events = pf_events + ca_events

    if args.limit:
        all_events = all_events[: args.limit]

    if not all_events:
        print("No unprocessed events found. Use --generate N to seed synthetic data.")
        sys.exit(0)

    print(f"\nProcessing {len(all_events)} event(s) "
          f"({len(pf_events)} payment failures, {len(ca_events)} abandonments)...\n")

    ok = skipped = 0
    for event, detect_fn in all_events:
        case = detect_fn(event)

        # Diagnose
        try:
            diagnosis = diagnose_mock(case) if args.mock_diagnosis else diagnose(case)
        except Exception as exc:
            # Surface the error type so auth failures aren't silent
            exc_type = type(exc).__name__
            print(f"  [WARN] diagnosis failed case={case.case_id[:8]} error={exc_type}: {str(exc)[:120]}")
            from data.models import DiagnosisResult
            diagnosis = DiagnosisResult(
                case_id=case.case_id, leak_type=case.leak_type,
                root_cause="unknown", confidence=0.0,
                recommended_intervention="suppress",
                reasoning=f"diagnosis_error={exc_type}",
                requires_human_escalation=False,
                diagnosis_corrected=True,
            )

        persist_diagnosis(diagnosis)

        if args.dry_run:
            from executor.workflow import persist_case
            from audit.writer import log_detection, log_diagnosis
            persist_case(case)
            log_detection(case)
            log_diagnosis(case, diagnosis)
            print(
                f"  [DRY] {case.case_id[:8]} "
                f"cause={diagnosis.root_cause} "
                f"intervention={diagnosis.recommended_intervention} "
                f"corrected={diagnosis.diagnosis_corrected}"
            )
            skipped += 1
            continue

        status = execute(case, diagnosis, suppress_list=suppress_list)
        print(
            f"  {case.case_id[:8]} "
            f"cause={diagnosis.root_cause:<20} "
            f"intervention={diagnosis.recommended_intervention:<28} "
            f"→ {status}"
        )
        ok += 1

    print(f"\nDone. processed={ok} dry_run_skipped={skipped}\n")
    print_summary(dry_run=args.dry_run)


if __name__ == "__main__":
    main()