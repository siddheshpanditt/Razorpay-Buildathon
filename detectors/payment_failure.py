"""
Reads unprocessed payment_failure_events from SQLite and emits Case objects.
An event is "unprocessed" if no case exists for its event_id yet.
"""
from datetime import datetime, timezone
from data.db import get_conn
from data.models import Case, PaymentFailureEvent


def load_unprocessed_events() -> list[PaymentFailureEvent]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM payment_failure_events
        WHERE event_id NOT IN (SELECT event_id FROM cases)
    """).fetchall()
    conn.close()
    return [
        PaymentFailureEvent(
            event_id=r["event_id"],
            customer_id=r["customer_id"],
            timestamp=datetime.fromisoformat(r["timestamp"]),
            amount=r["amount"],
            currency=r["currency"],
            payment_method=r["payment_method"],
            gateway_response_code=r["gateway_response_code"],
            attempt_number=r["attempt_number"],
            is_subscription_renewal=bool(r["is_subscription_renewal"]),
            customer_contact_opt_in=bool(r["customer_contact_opt_in"]),
            do_not_contact=bool(r["do_not_contact"]),
        )
        for r in rows
    ]


def detect(event: PaymentFailureEvent) -> Case:
    """Wrap a validated event in a Case ready for diagnosis."""
    return Case(
        leak_type="payment_failure",
        event_id=event.event_id,
        customer_id=event.customer_id,
        amount=event.amount,
        currency=event.currency,
        created_at=datetime.now(timezone.utc),
        raw_event=event.model_dump(mode="json"),
    )
