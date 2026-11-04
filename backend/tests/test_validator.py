from datetime import date

import pytest

from app.services.collections import templates as T
from app.services.collections.validator import allowed_facts, validate_draft


@pytest.fixture
def kestrel_ctx(customers, invoices, organization):
    cust = next(c for c in customers if c.customer_id == "C002")
    open_inv = [i for i in invoices if i.customer_id == "C002" and i.is_open()]
    return cust, open_inv, allowed_facts(cust, open_inv, organization, customers)


def test_kestrel_open_invoices_exclude_draft_and_paid(kestrel_ctx):
    _, open_inv, facts = kestrel_ctx
    assert sorted(i.invoice_number for i in open_inv) == ["INV-1004", "INV-1005"]
    assert facts.amounts_minor == {5900000, 11800000}


def test_facts_block_passes_validation(kestrel_ctx, organization):
    cust, open_inv, facts = kestrel_ctx
    block = T.facts_block(cust, open_inv, organization, date(2026, 11, 5))
    assert "INV-1004" in block and "INV-1005" in block and "₹1,18,000.00" in block
    assert "000111222333" in block and "EXMP0000142" in block
    body = "\n\n".join([T.greeting(cust), block, T.signature(organization)])
    assert validate_draft(body, facts).ok, validate_draft(body, facts).problems


@pytest.mark.parametrize(
    "text",
    [
        "Your balance on INV-1004 is Rs. 59,000.",
        "Total due 1,18,000.00 INR.",
        "INV 1005 is due on 20 Oct 2026.",
        "Due date: 2026-09-19.",
        "Due on September 19, 2026.",
        "Pay to account 000111222333, IFSC EXMP0000142, SWIFT: EXMPINBBXXX.",
        "We look forward to hearing from you within 3 working days.",
    ],
)
def test_valid_mentions(kestrel_ctx, text):
    assert validate_draft(text, kestrel_ctx[2]).ok


@pytest.mark.parametrize(
    "text,problem",
    [
        ("Please also pay INV-1006.", "INV-1006"),  # draft invoice of the same customer
        ("Please pay INV-1016.", "INV-1016"),  # another customer's invoice
        ("Your balance is ₹60,000.", "amount"),
        ("Your balance is 1,47,500.00.", "amount"),
        ("Due on 2026-10-31.", "date"),
        ("Due on 31/10/2026.", "date"),
        ("Pay to account 999988887777.", "account"),
        ("IFSC: HDFC0001234", "bank code"),
        ("SWIFT code: FAKEGB2LXXX", "bank code"),
        ("Balance USD 59,000.00", "currency"),
        ("Unlike Redwood Clinics, you owe little.", "another customer"),
    ],
)
def test_invalid_mentions(kestrel_ctx, text, problem):
    res = validate_draft(text, kestrel_ctx[2])
    assert not res.ok
    assert any(problem.lower() in p.lower() for p in res.problems), res.problems


def test_reminder_uses_balance_not_total(customers, invoices, organization):
    harbour = next(c for c in customers if c.customer_id == "C007")
    overdue = [i for i in invoices if i.customer_id == "C007" and i.is_overdue(date(2026, 11, 5))]
    body = T.reminder_body(organization, harbour, overdue, date(2026, 11, 5), 1)
    assert "$4,000.00" in body  # INV-1023 balance (total 6,000, 2,000 paid)
    assert "$6,000.00" not in body
    assert "INV-1023" in body and "INV-1021" in body and "INV-1022" in body


def test_today_is_allowed_only_when_passed(customers, invoices, organization):
    cust = next(c for c in customers if c.customer_id == "C002")
    open_inv = [i for i in invoices if i.customer_id == "C002" and i.is_open()]
    with_today = allowed_facts(cust, open_inv, organization, customers, date(2026, 11, 5))
    for text in ["As of 5 November 2026 your balance is below.", "As of 2026-11-05:"]:
        assert validate_draft(text, with_today).ok
        assert not validate_draft(text, allowed_facts(cust, open_inv, organization, customers)).ok
