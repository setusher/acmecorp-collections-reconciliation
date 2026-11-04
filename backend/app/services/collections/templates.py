"""Deterministic email text. Every figure customers see is produced here from DB data."""
from __future__ import annotations

from datetime import date

from app.core.money import format_amount
from app.models.domain import Customer, Invoice, Organization

FACTS_PLACEHOLDER = "{{FACTS}}"
SUBJECT_TAG = "[AcmeCorp]"


def fmt_date(d: date) -> str:
    return d.strftime("%d %b %Y")  # 19 Sep 2026: unambiguous across locales


def invoice_lines(invoices: list[Invoice], today: date) -> list[str]:
    lines = []
    for inv in sorted(invoices, key=lambda i: (i.due_date, i.invoice_number)):
        status = f"overdue by {inv.days_overdue(today)} days" if inv.is_overdue(today) else "not yet due"
        lines.append(
            f"  - {inv.invoice_number} | invoice date {fmt_date(inv.invoice_date)} | due {fmt_date(inv.due_date)}"
            f" | balance due {format_amount(inv.balance_minor, inv.currency)} ({status})"
        )
    return lines


def totals_line(invoices: list[Invoice]) -> str:
    by_cur: dict[str, int] = {}
    for inv in invoices:
        by_cur[inv.currency] = by_cur.get(inv.currency, 0) + inv.balance_minor
    return "  Total outstanding: " + ", ".join(format_amount(v, k) for k, v in sorted(by_cur.items()))


def bank_block(org: Organization) -> list[str]:
    b = org.bank_details
    lines = ["Bank details for payment:", f"  Account name: {b.account_name}", f"  Account number: {b.account_number}",
             f"  Bank: {b.bank}"]
    if b.ifsc:
        lines.append(f"  IFSC: {b.ifsc}")
    if b.swift_code:
        lines.append(f"  SWIFT: {b.swift_code}")
    lines.append(f"  Accepted methods: {', '.join(org.payment_methods)}")
    return lines


def facts_block(customer: Customer, open_invoices: list[Invoice], org: Organization, today: date,
                include_bank: bool = True) -> str:
    if open_invoices:
        lines = [f"Outstanding invoices for {customer.name}:", *invoice_lines(open_invoices, today),
                 totals_line(open_invoices)]
    else:
        lines = [f"Our records show no outstanding invoices for {customer.name}."]
    if include_bank:
        lines += ["", *bank_block(org)]
    if customer.country == "India" and open_invoices:
        lines += ["", f"TDS: {org.policies.get('tds', '')}".rstrip()]
    elif open_invoices and org.policies.get("bank_charges"):
        lines += ["", f"Bank charges: {org.policies['bank_charges']}"]
    return "\n".join(lines)


def signature(org: Organization) -> str:
    return f"Regards,\n{org.accounts_contact_name}\n{org.name}\n{org.accounts_email} | {org.phone}"


def greeting(customer: Customer | None) -> str:
    return f"Dear {customer.contact_name}," if customer else "Hello,"


REMINDER_TONES = {
    1: ("This is a friendly reminder that the following invoice(s) are past their due date.",
        "If you have already made the payment, please ignore this message or reply with the payment reference."),
    2: ("We have not yet received payment for the following overdue invoice(s).",
        "Please arrange payment at the earliest, or reply to this email if there is any issue we should know about."),
    3: ("Despite our earlier reminders, the following invoice(s) remain unpaid.",
        "Please make the payment within 7 days or contact the Accounts Team to discuss. "
        "Only the Accounts Team can agree a later payment date."),
}


def reminder_subject(org: Organization, customer: Customer, count: int) -> str:
    s = "s" if count != 1 else ""
    return f"{SUBJECT_TAG} Payment reminder: {count} overdue invoice{s} - {customer.name}"


def reminder_body(org: Organization, customer: Customer, overdue: list[Invoice], today: date,
                  reminder_number: int) -> str:
    intro, outro = REMINDER_TONES[min(max(reminder_number, 1), 3)]
    facts = facts_block(customer, overdue, org, today)
    return "\n\n".join([greeting(customer), intro, facts, outro, signature(org)])


def ack_paid_body(customer: Customer, org: Organization) -> str:
    return "\n\n".join([
        greeting(customer),
        "Thank you for letting us know. We have noted that you have made the payment. "
        "Our Accounts Team will match it against your invoice once it appears in our bank statement, "
        "and we will update our records then. If you have a payment reference, please share it.",
        signature(org),
    ])


def ack_promise_body(customer: Customer, org: Organization) -> str:
    return "\n\n".join([
        greeting(customer),
        "Thank you for the update. We have noted your intended payment date. "
        "The invoice remains outstanding until the payment is received, and we will update our records then.",
        signature(org),
    ])


def holding_reply_body(customer: Customer | None, org: Organization) -> str:
    """Draft offered to humans for messages the agent must not answer itself."""
    return "\n\n".join([
        greeting(customer),
        "Thank you for your email. A member of our Accounts Team will review it and get back to you shortly.",
        signature(org),
    ])


def reply_subject(subject: str) -> str:
    subject = (subject or "").strip()
    return subject if subject.lower().startswith("re:") else f"Re: {subject}" if subject else f"Re: {SUBJECT_TAG}"
