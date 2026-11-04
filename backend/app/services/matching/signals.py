"""Amount and date signals. All amounts are integer minor units; comparisons are exact.

No tolerance for bank fees: the organisation's policy says international
customers cover their own bank charges in full, so a short SWIFT receipt is a
shortfall for a human to review, not something to absorb silently.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from app.core.money import format_amount, tds_minor
from app.models.domain import Invoice

AmountKind = Literal["balance", "total", "tds", "instalment", "partial_declared", "partial", "over"]

# Points (out of ~100) contributed by each amount outcome.
AMOUNT_POINTS: dict[str, int] = {
    "balance": 40,  # receipt equals the open balance exactly
    "total": 30,  # equals invoice total but not the balance (unusual: earlier part payment)
    "tds": 35,  # equals balance minus 10% TDS on subtotal (INR only)
    "instalment": 22,  # partial that equals a known instalment pattern
    "partial_declared": 25,  # partial and narration says PART/ADVANCE/INSTALMENT
    "partial": 8,  # smaller than balance, no other explanation
    "over": 0,  # larger than balance: cannot be applied to this invoice alone
}


@dataclass(frozen=True)
class AmountSignal:
    kind: AmountKind
    points: int
    tds_minor: int  # TDS that would close the invoice (only for kind == "tds")
    text: str


def tds_expected(inv: Invoice) -> int:
    """Expected TDS for an invoice, or 0 if TDS is not plausible.

    Plausible only for INR invoices with no previous payment/TDS (policy: Indian
    customers may deduct 10% of the subtotal).
    """
    if inv.currency != "INR" or inv.amount_paid_minor or inv.tds_minor:
        return 0
    return tds_minor(inv.subtotal_minor)


def amount_signal(amount: int, inv: Invoice, partial_hint: bool) -> AmountSignal:
    cur = inv.currency
    bal = inv.balance_minor
    if amount == bal:
        return AmountSignal("balance", AMOUNT_POINTS["balance"], 0, "amount equals balance")
    tds = tds_expected(inv)
    if tds and amount == bal - tds:
        return AmountSignal(
            "tds", AMOUNT_POINTS["tds"], tds,
            f"amount equals balance less 10% TDS on subtotal ({format_amount(tds, cur)})",
        )
    if amount > bal:
        if amount == inv.total_minor:
            return AmountSignal("total", AMOUNT_POINTS["over"], 0, "amount equals invoice total but exceeds balance")
        return AmountSignal("over", AMOUNT_POINTS["over"], 0, "amount exceeds balance")
    # amount < balance from here
    if inv.amount_paid_minor and amount == inv.amount_paid_minor:
        return AmountSignal("instalment", AMOUNT_POINTS["instalment"], 0, "partial: same as the previous instalment")
    for k in (2, 3, 4):
        if amount * k == inv.total_minor:
            return AmountSignal("instalment", AMOUNT_POINTS["instalment"], 0, f"partial: exactly 1/{k} of invoice total")
    if partial_hint:
        return AmountSignal("partial_declared", AMOUNT_POINTS["partial_declared"], 0,
                            "partial payment (narration says part/advance)")
    return AmountSignal("partial", AMOUNT_POINTS["partial"], 0, "amount is less than balance")


@dataclass(frozen=True)
class DateSignal:
    points: int
    text: str | None


def date_signal(txn_date: date, inv: Invoice) -> DateSignal:
    if txn_date < inv.invoice_date:
        days = (inv.invoice_date - txn_date).days
        return DateSignal(-50, f"payment is {days} day(s) before the invoice date")
    late = (txn_date - inv.due_date).days
    # A flat window on purpose: small date differences are noise, so equal-amount
    # invoices tie here and the engine falls back to oldest-due-first.
    if late <= 90:
        return DateSignal(5, None)
    if late <= 365:
        return DateSignal(2, None)
    return DateSignal(-3, f"payment is {late} days after the due date")
