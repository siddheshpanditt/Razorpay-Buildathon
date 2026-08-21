"""
Mocked channel stubs. Each returns a delivery receipt dict.
Swap these out for real integrations without touching the executor.
"""
from datetime import datetime, timezone


def _receipt(channel: str, case_id: str, status: str, meta: dict) -> dict:
    return {
        "channel": channel,
        "case_id": case_id,
        "status": status,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        **meta,
    }


def send_email(case_id: str, customer_id: str, template: str, payload: dict) -> dict:
    print(f"  [EMAIL] case={case_id} customer={customer_id} template={template}")
    return _receipt("email", case_id, "sent", {"template": template})


def send_sms(case_id: str, customer_id: str, message: str) -> dict:
    print(f"  [SMS]   case={case_id} customer={customer_id} msg={message[:60]}")
    return _receipt("sms", case_id, "sent", {"message_preview": message[:60]})


def send_webhook(case_id: str, event_type: str, payload: dict) -> dict:
    print(f"  [WEBHOOK] case={case_id} event={event_type}")
    return _receipt("webhook", case_id, "sent", {"event_type": event_type})


def escalate_to_human(case_id: str, customer_id: str, reason: str) -> dict:
    print(f"  [ESCALATE] case={case_id} customer={customer_id} reason={reason}")
    return _receipt("human_queue", case_id, "queued", {"reason": reason})
