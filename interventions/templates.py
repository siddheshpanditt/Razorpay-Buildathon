"""
Message templates per intervention type.
Returns (channel, template_name, message_text) for the executor to dispatch.
"""

_TEMPLATES: dict[str, tuple[str, str, str]] = {
    # payment_failure interventions
    "retry_now": (
        "webhook",
        "payment_retry_now",
        "Retrying your payment automatically.",
    ),
    "retry_scheduled": (
        "webhook",
        "payment_retry_scheduled",
        "We'll retry your payment in a few hours.",
    ),
    "request_payment_update": (
        "email",
        "payment_update_request",
        "Your payment didn't go through. Please update your payment method to complete your order.",
    ),
    "offer_alternate_method": (
        "sms",
        "alternate_payment_method",
        "Having trouble paying? Try UPI, netbanking, or a different card.",
    ),
    # checkout_abandonment interventions
    "reminder_nudge": (
        "email",
        "checkout_reminder",
        "You left something in your cart. Complete your purchase before it sells out.",
    ),
    "discount_offer": (
        "email",
        "checkout_discount",
        "Still thinking it over? Here's 10% off to complete your order.",
    ),
    "simplify_checkout_flag": (
        "webhook",
        "simplify_checkout",
        "Flagging checkout flow for simplification review.",
    ),
    # shared
    "escalate_human": (
        "human_queue",
        "human_escalation",
        "Case requires manual review.",
    ),
    "suppress": (
        "none",
        "suppress",
        "Case suppressed — no contact.",
    ),
}


def get_template(intervention: str) -> tuple[str, str, str]:
    """Returns (channel, template_name, message_text). Falls back to suppress."""
    return _TEMPLATES.get(intervention, _TEMPLATES["suppress"])
