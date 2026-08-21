"""
Reads unprocessed checkout_abandonment_events from SQLite and emits Case objects.
"""
from datetime import datetime, timezone
from data.db import get_conn
from data.models import Case, CheckoutAbandonmentEvent


def load_unprocessed_events() -> list[CheckoutAbandonmentEvent]:
    conn = get_conn()
    rows = conn.execute("""
        SELECT * FROM checkout_abandonment_events
        WHERE event_id NOT IN (SELECT event_id FROM cases)
    """).fetchall()
    conn.close()
    return [
        CheckoutAbandonmentEvent(
            event_id=r["event_id"],
            customer_id=r["customer_id"],
            timestamp=datetime.fromisoformat(r["timestamp"]),
            cart_value=r["cart_value"],
            currency=r["currency"],
            stage_reached=r["stage_reached"],
            device_type=r["device_type"],
            time_since_last_activity_minutes=r["time_since_last_activity_minutes"],
            is_repeat_customer=bool(r["is_repeat_customer"]),
            customer_contact_opt_in=bool(r["customer_contact_opt_in"]),
            do_not_contact=bool(r["do_not_contact"]),
        )
        for r in rows
    ]


def detect(event: CheckoutAbandonmentEvent) -> Case:
    return Case(
        leak_type="checkout_abandonment",
        event_id=event.event_id,
        customer_id=event.customer_id,
        amount=event.cart_value,   # unified field name across leak types
        currency=event.currency,
        created_at=datetime.now(timezone.utc),
        raw_event=event.model_dump(mode="json"),
    )
