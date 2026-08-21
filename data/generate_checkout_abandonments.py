"""
Generates synthetic CheckoutAbandonmentEvents and persists them to SQLite.
Usage: python data/generate_checkout_abandonments.py --count 50
"""
import argparse
import random
import uuid
from datetime import datetime, timedelta, timezone

from data.db import get_conn
from data.models import CheckoutAbandonmentEvent

_STAGES = ["cart", "shipping_info", "payment_info", "otp_verification"]
_STAGE_WEIGHTS = [0.20, 0.15, 0.35, 0.30]   # most drop at payment/otp

_DEVICES = ["mobile", "desktop"]
_DEVICE_WEIGHTS = [0.68, 0.32]

_CART_VALUES = [199, 499, 799, 999, 1499, 2499, 3999, 5999, 9999, 14999, 24999]


def _random_event(dnc_rate: float = 0.05, no_optin_rate: float = 0.08) -> CheckoutAbandonmentEvent:
    ts = datetime.now(timezone.utc) - timedelta(minutes=random.randint(10, 2880))
    return CheckoutAbandonmentEvent(
        event_id=str(uuid.uuid4()),
        customer_id=f"cust_{random.randint(1000, 9999)}",
        timestamp=ts,
        cart_value=float(random.choice(_CART_VALUES)),
        currency="INR",
        stage_reached=random.choices(_STAGES, weights=_STAGE_WEIGHTS)[0],
        device_type=random.choices(_DEVICES, weights=_DEVICE_WEIGHTS)[0],
        time_since_last_activity_minutes=random.randint(15, 480),
        is_repeat_customer=random.random() < 0.35,
        customer_contact_opt_in=random.random() > no_optin_rate,
        do_not_contact=random.random() < dnc_rate,
    )


def generate(count: int = 50) -> list[CheckoutAbandonmentEvent]:
    events = [_random_event() for _ in range(count)]
    conn = get_conn()
    conn.executemany(
        "INSERT OR IGNORE INTO checkout_abandonment_events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (
                e.event_id, e.customer_id, e.timestamp.isoformat(),
                e.cart_value, e.currency, e.stage_reached,
                e.device_type, e.time_since_last_activity_minutes,
                int(e.is_repeat_customer), int(e.customer_contact_opt_in),
                int(e.do_not_contact),
            )
            for e in events
        ],
    )
    conn.commit()
    conn.close()
    print(f"Inserted {count} checkout abandonment events.")
    return events


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=50)
    args = parser.parse_args()
    generate(args.count)
