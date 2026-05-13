"""
backend/services/email_service.py
─────────────────────────────────
Email-verzending voor magic links en latere notificaties.

Werkt in twee modi:
  1. PRODUCTION  — Resend API (verzend echte emails)
  2. DEVELOPMENT — log de email naar console + schrijf naar /tmp/youcaps_emails.log

Schakelen gebeurt via de RESEND_API_KEY env-var. Aanwezig → production.
Afwezig → development.

Setup productie:
  - Maak een account op resend.com (gratis tot 3000 mails/maand)
  - Verifieer je domein (youcaps.ai) of gebruik onboarding@resend.dev voor testen
  - Zet RESEND_API_KEY in .env
  - Zet EMAIL_FROM in .env (bijv. "Youcaps <login@youcaps.ai>")

Voeg toe aan requirements.txt:
  resend>=2.0.0,<3.0.0
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# ─── Config ──────────────────────────────────────────────────────────────
RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
EMAIL_FROM = os.getenv("EMAIL_FROM", "Youcaps <onboarding@resend.dev>").strip()
DEV_LOG_PATH = Path("/tmp/youcaps_emails.log")

# Resend wordt lazy geïmporteerd; zo crasht de server niet bij ontbrekende package
_resend = None


def _get_resend():
    global _resend
    if _resend is None:
        try:
            import resend  # type: ignore
            resend.api_key = RESEND_API_KEY
            _resend = resend
        except ImportError as e:
            raise RuntimeError(
                "Package 'resend' is niet geïnstalleerd. "
                "Voeg toe aan requirements.txt: resend>=2.0.0"
            ) from e
    return _resend


def is_production() -> bool:
    return bool(RESEND_API_KEY)


# ─── Public API ──────────────────────────────────────────────────────────

def send_magic_link(email: str, link_url: str) -> None:
    """
    Verstuur een magic-link email. In dev-modus wordt de link naar console
    gelogd en in /tmp/youcaps_emails.log geschreven, zodat je kunt testen
    zonder Resend-account.
    """
    subject = "Inloggen bij Youcaps"
    text_body = _magic_link_text(link_url)
    html_body = _magic_link_html(link_url)

    if not is_production():
        _dev_log_email(email, subject, link_url, text_body)
        return

    try:
        resend = _get_resend()
        resend.Emails.send({
            "from": EMAIL_FROM,
            "to": [email],
            "subject": subject,
            "html": html_body,
            "text": text_body,
        })
        logger.info("Magic link verzonden naar %s", email)
    except Exception as e:
        logger.exception("Magic link verzenden mislukt voor %s: %s", email, e)
        # In dev fallback ook op console zodat de developer zelf verder kan
        _dev_log_email(email, subject, link_url, text_body, error=str(e))
        raise


# ─── Templates ───────────────────────────────────────────────────────────

def _magic_link_text(link_url: str) -> str:
    return (
        "Inloggen bij Youcaps\n"
        "\n"
        "Klik op de link hieronder om in te loggen:\n"
        f"{link_url}\n"
        "\n"
        "Deze link is 15 minuten geldig en werkt eenmalig.\n"
        "\n"
        "Heb je deze email niet aangevraagd? Negeer 'm dan.\n"
        "\n"
        "Youcaps.ai\n"
        "Jouw lichaam. Jouw formule.\n"
    )


def _magic_link_html(link_url: str) -> str:
    # Minimal, huisstijl-conform (geen kleur, Fraunces met fallback Times,
    # IBM Plex Mono met fallback monospace).
    return f"""<!DOCTYPE html>
<html lang="nl">
<head>
<meta charset="UTF-8">
<title>Inloggen bij Youcaps</title>
</head>
<body style="margin:0;padding:40px 20px;background:#ffffff;font-family:'Times New Roman',Georgia,serif;color:#0A0A0A;">
  <div style="max-width:480px;margin:0 auto;">
    <p style="font-family:'Courier New',monospace;font-size:11px;letter-spacing:0.05em;text-transform:uppercase;color:#888;margin:0 0 32px;">
      YOUCAPS.AI
    </p>
    <h1 style="font-size:32px;font-weight:400;letter-spacing:-0.4px;margin:0 0 16px;line-height:1.2;">
      Inloggen
    </h1>
    <p style="font-size:15px;line-height:1.7;color:#0A0A0A;margin:0 0 32px;">
      Klik op de link om in te loggen. De link is 15 minuten geldig en werkt eenmalig.
    </p>
    <p style="margin:0 0 40px;">
      <a href="{link_url}" style="font-size:15px;color:#0A0A0A;text-decoration:underline;">
        Inloggen bij Youcaps →
      </a>
    </p>
    <p style="font-size:13px;color:#888;line-height:1.6;margin:0 0 8px;">
      Werkt de link niet? Plak deze in je browser:
    </p>
    <p style="font-family:'Courier New',monospace;font-size:11px;color:#888;word-break:break-all;line-height:1.6;margin:0 0 40px;">
      {link_url}
    </p>
    <hr style="border:none;border-top:1px solid #f0f0f0;margin:0 0 24px;">
    <p style="font-size:13px;color:#888;line-height:1.6;margin:0;">
      Heb je deze email niet aangevraagd? Negeer 'm dan.
    </p>
  </div>
</body>
</html>"""


# ─── Dev-mode logging ────────────────────────────────────────────────────

def _dev_log_email(email: str, subject: str, link_url: str, body: str, error: str | None = None) -> None:
    timestamp = datetime.utcnow().isoformat()
    banner = "═" * 60
    msg = (
        f"\n{banner}\n"
        f"[DEV EMAIL] {timestamp}\n"
        f"  TO:      {email}\n"
        f"  SUBJECT: {subject}\n"
        f"  LINK:    {link_url}\n"
    )
    if error:
        msg += f"  ERROR:   {error}\n"
    msg += f"{banner}\n"

    # Log naar console
    logger.info(msg)
    print(msg, flush=True)

    # Log naar bestand
    try:
        DEV_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with DEV_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(msg)
            f.write(body)
            f.write("\n\n")
    except OSError:
        pass
