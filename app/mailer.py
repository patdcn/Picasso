"""
Tiny SMTP helper for outbound notifications (e.g. access requests to admins).

Email is OPTIONAL: if SMTP isn't configured the app still works — callers should
treat a False return as "couldn't notify" and rely on the database record instead.

Configure via environment variables (set in the Dokploy UI, not committed):
  SMTP_HOST        smtp server hostname            (required to enable email)
  SMTP_PORT        port (default 587; use 465 for implicit SSL)
  SMTP_USER        login username (optional)
  SMTP_PASSWORD    login password (optional)
  SMTP_FROM        From: address (default = SMTP_USER)
  SMTP_USE_TLS     "true" (default) to STARTTLS on non-465 ports
"""
import os
import ssl
import smtplib
from email.message import EmailMessage


def is_configured():
    return bool((os.getenv("SMTP_HOST") or "").strip())


def send_email(subject, body, to_list, reply_to=None):
    """Send a plain-text email. Returns (ok, message). Never raises."""
    host = (os.getenv("SMTP_HOST") or "").strip()
    if not host:
        return False, "Email not configured (SMTP_HOST unset)."
    to_list = [t for t in (to_list or []) if t]
    if not to_list:
        return False, "No recipient address."

    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    pw = os.getenv("SMTP_PASSWORD")
    sender = (os.getenv("SMTP_FROM") or user or "noreply@localhost").strip()
    use_tls = (os.getenv("SMTP_USE_TLS", "true").lower() == "true")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(to_list)
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=15) as s:
                if user and pw:
                    s.login(user, pw)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                if use_tls:
                    s.starttls(context=ssl.create_default_context())
                if user and pw:
                    s.login(user, pw)
                s.send_message(msg)
        return True, "Email sent."
    except Exception as e:
        return False, f"Email send failed: {e}"
