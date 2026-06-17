"""
WhatsApp notification sender using Twilio.

Set credentials in .env — if not configured, messages are logged instead of sent.
"""

import os
import logging

log = logging.getLogger(__name__)


def send_whatsapp(to: str, body: str) -> bool:
    """
    Send a WhatsApp message via Twilio.
    Returns True on success, False on failure.
    Falls back to logging if Twilio credentials are not set.
    """
    sid   = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    from_ = os.getenv("TWILIO_WHATSAPP_FROM", "")

    if not sid or sid.startswith("AC" + "x") or not token or token == "your_auth_token_here":
        log.warning("[notifier] Twilio not configured — printing message instead:\n%s", body)
        print(f"\n{'='*60}\n[WhatsApp → {to}]\n{body}\n{'='*60}\n")
        return False

    try:
        from twilio.rest import Client
        client = Client(sid, token)
        client.messages.create(from_=from_, to=to, body=body)
        log.info("[notifier] WhatsApp sent to %s", to)
        return True
    except Exception as exc:
        log.error("[notifier] Failed to send WhatsApp to %s: %s", to, exc)
        return False
