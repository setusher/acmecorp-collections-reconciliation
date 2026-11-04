"""Send overdue reminders: one email per customer listing all their overdue invoices."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from app.core import clock
from app.core.config import Settings
from app.integrations.smtp import Mailer, MailError, OutgoingMail
from app.repositories import Repos
from app.services.collections import templates as T

PLACEHOLDER_DOMAINS = ("example.com", "example.org", "example.net")
IST = timezone(timedelta(hours=5, minutes=30))


def within_working_hours(now: datetime) -> bool:
    """Policy: Monday to Friday, 10:00 to 18:00 IST (used for scheduled runs)."""
    local = now.astimezone(IST)
    return local.weekday() < 5 and 10 <= local.hour < 18


async def send_reminders(repos: Repos, mailer: Mailer, settings: Settings, actor: str,
                         scheduled: bool = False) -> dict:
    org = await repos.master.get_organization()
    if org is None:
        raise RuntimeError("organization not seeded")
    if scheduled and not within_working_hours(clock.now()):
        return {"sent": [], "skipped": [{"reason": "outside working hours (Mon-Fri 10:00-18:00 IST)"}]}
    today = clock.today()
    sent, skipped = [], []
    for customer in await repos.master.list_customers():
        overdue = [i for i in await repos.master.open_invoices(customer.customer_id) if i.is_overdue(today)]
        if not overdue:
            continue
        base = {"customer_id": customer.customer_id, "customer": customer.name,
                "invoices": [i.invoice_number for i in overdue]}
        if customer.contact_email.split("@")[-1] in PLACEHOLDER_DOMAINS:
            skipped.append({**base, "reason": f"placeholder address {customer.contact_email}: update it first"})
            continue
        conv = await repos.collections.latest_conversation_for_customer(customer.customer_id)
        if conv and conv.get("status") == "needs_attention":
            # e.g. an open dispute or extension request: a human answers first, the agent does not chase.
            skipped.append({**base, "reason": "conversation is waiting in Needs attention"})
            continue
        last = conv.get("last_reminder_at") if conv else None
        if isinstance(last, datetime):
            if last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
            next_due = last + timedelta(days=settings.reminder_interval_days)
            if clock.now() < next_due:
                skipped.append({**base, "reason": f"reminded {last.date().isoformat()}; next reminder after "
                                                  f"{next_due.date().isoformat()}"})
                continue
        count = (conv.get("reminder_count", 0) if conv else 0) + 1
        subject = T.reminder_subject(org, customer, len(overdue))
        body = T.reminder_body(org, customer, overdue, today, count)
        if conv is None or conv.get("status") == "resolved":
            conv = await repos.collections.create_conversation(customer.customer_id, subject)
        last_out = await repos.collections.last_outbound(conv["_id"])
        try:
            mid = await mailer.send(OutgoingMail(customer.contact_email, subject, body,
                                                 in_reply_to=last_out["message_id"] if last_out else None,
                                                 auto_submitted="auto-generated"))
        except MailError as exc:
            skipped.append({**base, "reason": str(exc)})
            continue
        now = clock.now()
        await repos.collections.insert_message({
            "message_id": mid, "conversation_id": conv["_id"], "direction": "out", "kind": "reminder",
            "from_addr": org.accounts_email, "to_addr": customer.contact_email, "subject": subject,
            "body_text": body, "auto_sent": True, "category": None, "invoice_numbers": base["invoices"],
        })
        await repos.collections.update_conversation(conv["_id"], {
            "last_reminder_at": now, "reminder_count": count, "subject": subject,
            "status": "open"})
        await repos.audit.log(actor, "reminder_sent", f"customer:{customer.customer_id}",
                              {"to": customer.contact_email, "invoices": base["invoices"], "message_id": mid,
                               "reminder_number": count})
        sent.append({**base, "to": customer.contact_email, "reminder_number": count})
    return {"sent": sent, "skipped": skipped}
