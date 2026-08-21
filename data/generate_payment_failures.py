"""
Generates synthetic PaymentFailureEvents and persists them to SQLite.
Usage: python data/generate_payment_failures.py --count 50
"""
import argparse
import random
import uuid
from datetime import datetime, timedelta, timezone

from data.db import get_conn
from data.models import PaymentFailureEvent


# Weighted so the distribution looks realistic
_METHODS = ["card", "upi", "netbanking", "wallet"]
_METHOD_WEIGHTS = [0.45, 0.35, 0.12, 0.08]

_CODES = [
    "insufficient_funds", "expired_card", "issuer_decline",
    "gateway_timeout", "do_not_honor", "fraud_flagged", "unknown"
]
_CODE_WEIGHTS = [0.28, 0.15, 0.22, 0.12, 0.10, 0.05, 0.08]

_AMOUNTS = [199, 499, 999, 1499, 2999, 4999, 9999, 14999, 29999, 49999, 99999]


def _random_event(dnc_rate: float = 0.05, no_optin_rate: float = 0.08) -> PaymentFailureEvent:
    ts = datetime.now(timezone.utc) - timedelta(minutes=random.randint(5, 1440))
    return PaymentFailureEvent(
        event_id=str(uuid.uuid4()),
        customer_id=f"cust_{random.randint(1000, 9999)}",
        timestamp=ts,
        amount=float(random.choice(_AMOUNTS)),
        currency="INR",
        payment_method=random.choices(_METHODS, weights=_METHOD_WEIGHTS)[0],
        gateway_response_code=random.choices(_CODES, weights=_CODE_WEIGHTS)[0],
        attempt_number=random.choices([1, 2, 3], weights=[0.70, 0.22, 0.08])[0],
        is_subscription_renewal=random.random() < 0.20,
        customer_contact_opt_in=random.random() > no_optin_rate,
        do_not_contact=random.random() < dnc_rate,
    )


def generate(count: int = 50) -> list[PaymentFailureEvent]:
    events = [_random_event() for _ in range(count)]
    conn = get_conn()
    conn.executemany(
        """INSERT OR IGNORE INTO payment_failure_events VALUES
           (?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (
                e.event_id, e.customer_id, e.timestamp.isoformat(),
                e.amount, e.currency, e.payment_method,
                e.gateway_response_code, e.attempt_number,
                int(e.is_subscription_renewal),
                int(e.customer_contact_opt_in),
                int(e.do_not_contact),
            )
            for e in events
        ],
    )
    conn.commit()
    conn.close()
    print(f"Inserted {count} payment failure events.")
    return events


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=50)
    args = parser.parse_args()
    generate(args.count)
