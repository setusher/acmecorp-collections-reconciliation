"""Validate an outgoing draft against the facts the customer is allowed to see.

Every invoice number, amount, date, account number and bank code found in the
draft must belong to the matched customer's allowed set. Parsing is
format-tolerant (INV 1004 / INV-1004, 59,000 / 59000.00 / Rs. 59000,
19 Sep 2026 / 2026-09-19 / 19/09/2026).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

from app.core.money import to_minor
from app.models.domain import Customer, Invoice, Organization
from app.services.matching.normalize import name_tokens

_INV = re.compile(r"\bINV(?:OICE)?(?:\s*NO\.?)?[\s\-/#:.]*0*(\d{3,6})\b", re.IGNORECASE)
_CUR = r"(?:₹|Rs\.?|INR|\$|USD|US\$|€|EUR|£|GBP)"
_NUM = r"(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d{1,2})?"
_AMT_WITH_CUR = re.compile(rf"(?:{_CUR}\s*({_NUM}))|(?:({_NUM})\s*{_CUR})", re.IGNORECASE)
_AMT_GROUPED = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?)(?![\w,])")
_AMT_DECIMAL = re.compile(r"(?<![\w.,])(\d+\.\d{2})(?![\w.])")
_LONG_DIGITS = re.compile(r"(?<!\d)(\d{9,18})(?!\d)")
_IFSC = re.compile(r"\b([A-Z]{4}0[A-Z0-9]{6})\b")
_LABELLED_CODE = re.compile(
    r"\b(?:SWIFT|BIC|IFSC)(?:\s*/\s*BIC)?(?:\s*code)?\s*[:\-]?\s*"
    r"(?-i:([A-Z]{4}0[A-Z0-9]{6}|[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?))\b",
    re.IGNORECASE,
)
_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|january|february|march|april|june|july|august|september|october|november|december"
_DATE_PATTERNS = [
    (re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"), ("%Y-%m-%d",)),
    (re.compile(r"\b(\d{1,2}/\d{1,2}/\d{4})\b"), ("%d/%m/%Y",)),
    (re.compile(r"\b(\d{1,2}-\d{1,2}-\d{4})\b"), ("%d-%m-%Y",)),
    (re.compile(rf"\b(\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{_MONTHS})\.?,?\s+\d{{4}})\b", re.IGNORECASE),
     ("%d %b %Y", "%d %B %Y")),
    (re.compile(rf"\b((?:{_MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}})\b", re.IGNORECASE),
     ("%b %d %Y", "%B %d %Y")),
]


@dataclass
class AllowedFacts:
    invoice_numbers: set[int]
    amounts_minor: set[int]
    dates: set[date]
    account_numbers: set[str]
    bank_codes: set[str]
    phone_digits: set[str]
    currency: str
    other_customer_tokens: set[str] = field(default_factory=set)


@dataclass
class ValidationResult:
    ok: bool
    problems: list[str]


def allowed_facts(customer: Customer, open_invoices: list[Invoice], org: Organization,
                  all_customers: list[Customer]) -> AllowedFacts:
    amounts = {i.balance_minor for i in open_invoices}
    if open_invoices:
        amounts.add(sum(i.balance_minor for i in open_invoices))
    dates = {i.due_date for i in open_invoices} | {i.invoice_date for i in open_invoices}
    nums = set()
    for i in open_invoices:
        m = re.search(r"(\d+)$", i.invoice_number)
        if m:
            nums.add(int(m.group(1)))
    bd = org.bank_details
    own = set(name_tokens(customer.name))
    others = set()
    for c in all_customers:
        if c.customer_id != customer.customer_id:
            others.update(t for t in name_tokens(c.name) if len(t) >= 5 and t not in own)
    return AllowedFacts(
        invoice_numbers=nums,
        amounts_minor=amounts,
        dates=dates,
        account_numbers={bd.account_number},
        bank_codes={c for c in (bd.ifsc, bd.swift_code) if c},
        phone_digits={re.sub(r"\D", "", org.phone)},
        currency=customer.currency,
        other_customer_tokens=others - _COMMON_WORDS,
    )


# Business words that may legitimately appear in any reply.
_COMMON_WORDS = {"RETAIL", "MEDIA", "FOODS", "ANALYTICS", "LOGISTICS", "PACKAGING", "CLINICS", "HOSPITALITY",
                 "TECHNOLOGIES", "SERVICES"}


def _parse_date(text: str, fmts: tuple[str, ...]) -> date | None:
    clean = re.sub(r"(\d)(st|nd|rd|th)", r"\1", text, flags=re.IGNORECASE).replace(",", "").replace(".", "")
    clean = re.sub(r"\bsept\b", "sep", clean, flags=re.IGNORECASE)
    clean = " ".join(clean.split())
    for fmt in fmts:
        try:
            return datetime.strptime(clean, fmt).date()
        except ValueError:
            continue
    return None


def validate_draft(text: str, facts: AllowedFacts) -> ValidationResult:
    problems: list[str] = []

    for m in _INV.finditer(text):
        if int(m.group(1)) not in facts.invoice_numbers:
            problems.append(f"mentions invoice {m.group(0).strip()} which is not an open invoice of this customer")

    # Mask things that are not amounts (phone numbers, account numbers, dates) before amount scanning.
    masked = text
    for pd in facts.phone_digits:
        masked = re.sub(r"\+?\d[\d\s]{6,}\d",
                        lambda mm, pd=pd: " " if re.sub(r"\D", "", mm.group(0)) == pd else mm.group(0), masked)
    for pattern, _ in _DATE_PATTERNS:
        masked = pattern.sub(" ", masked)

    seen_spans: list[tuple[int, int]] = []
    for m in _AMT_WITH_CUR.finditer(masked):
        raw = m.group(1) or m.group(2)
        seen_spans.append(m.span())
        _check_amount(raw, m.group(0), facts, problems)
    for rx in (_AMT_GROUPED, _AMT_DECIMAL):
        for m in rx.finditer(masked):
            if any(s <= m.start() < e for s, e in seen_spans):
                continue
            seen_spans.append(m.span())
            _check_amount(m.group(1), m.group(0), facts, problems)
    for m in re.finditer(rf"({_CUR})\s*{_NUM}", masked, re.IGNORECASE):
        cur = m.group(1).upper().replace("RS.", "INR").replace("RS", "INR")
        symbol_map = {"₹": "INR", "$": "USD", "US$": "USD", "€": "EUR", "£": "GBP"}
        cur = symbol_map.get(m.group(1), cur)
        if cur != facts.currency:
            problems.append(f"mentions currency {m.group(1)} but the customer is billed in {facts.currency}")

    for pattern, fmts in _DATE_PATTERNS:
        for m in pattern.finditer(text):
            d = _parse_date(m.group(1), fmts)
            if d is None or d not in facts.dates:
                problems.append(f"mentions date '{m.group(1)}' which is not an invoice/due date of this customer")

    for m in _LONG_DIGITS.finditer(text):
        if m.group(1) not in facts.account_numbers and m.group(1) not in facts.phone_digits:
            problems.append(f"mentions account-like number {m.group(1)} that is not the organisation's account")
    codes = {m.group(1) for m in _IFSC.finditer(text)}  # IFSC shape is distinctive anywhere
    codes |= {m.group(1) for m in _LABELLED_CODE.finditer(text)}  # "SWIFT: XXXX", "BIC XXXX", "IFSC: XXXX"
    for code in sorted(codes):
        if code not in facts.bank_codes:
            problems.append(f"mentions bank code {code} that differs from the organisation's bank details")

    upper = text.upper()
    for tok in facts.other_customer_tokens:
        if re.search(rf"\b{re.escape(tok)}\b", upper):
            problems.append(f"mentions '{tok.title()}', which looks like another customer's name")

    return ValidationResult(not problems, sorted(set(problems)))


def _check_amount(raw: str, shown: str, facts: AllowedFacts, problems: list[str]) -> None:
    try:
        minor = to_minor(raw.replace(",", ""))
    except ValueError:
        problems.append(f"unparseable amount {shown.strip()}")
        return
    if minor not in facts.amounts_minor:
        problems.append(f"mentions amount {shown.strip()} which is not a balance (or total) of this customer")
