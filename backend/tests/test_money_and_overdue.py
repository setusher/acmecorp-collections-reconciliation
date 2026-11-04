from datetime import date

import pytest

from app.core import clock
from app.core.money import format_amount, tds_minor, to_minor


@pytest.mark.parametrize(
    "value,expected",
    [(7350.5, 735050), ("2,36,000.00".replace(",", ""), 23600000), (0.1, 10), (59000, 5900000), ("431.22", 43122)],
)
def test_to_minor(value, expected):
    assert to_minor(value) == expected


def test_to_minor_rejects_garbage():
    with pytest.raises(ValueError):
        to_minor("abc")
    with pytest.raises(ValueError):
        to_minor(True)


@pytest.mark.parametrize(
    "minor,cur,expected",
    [
        (11800000, "INR", "₹1,18,000.00"),
        (35400000, "INR", "₹3,54,000.00"),
        (1234567800, "INR", "₹1,23,45,678.00"),
        (99900, "INR", "₹999.00"),
        (1250000, "USD", "$12,500.00"),
        (735050, "GBP", "£7,350.50"),
        (920000, "EUR", "€9,200.00"),
        (-5000, "INR", "-₹50.00"),
    ],
)
def test_format_amount(minor, cur, expected):
    assert format_amount(minor, cur) == expected


def test_tds_is_ten_percent_of_subtotal():
    # Spec example: total 3,54,000, subtotal 3,00,000 -> TDS 30,000 -> expected 3,24,000
    assert tds_minor(to_minor(300000)) == to_minor(30000)
    assert to_minor(354000) - tds_minor(to_minor(300000)) == to_minor(324000)


def test_clock_reads_env(monkeypatch):
    monkeypatch.setenv("APP_AS_OF_DATE", "2026-01-31")
    assert clock.today() == date(2026, 1, 31)


EXPECTED_OVERDUE = {
    "INV-1002", "INV-1004", "INV-1005", "INV-1007", "INV-1008", "INV-1010", "INV-1011", "INV-1012",
    "INV-1013", "INV-1016", "INV-1017", "INV-1021", "INV-1022", "INV-1023", "INV-1024", "INV-1026",
}


def test_overdue_as_of_2026_11_05(invoices):
    today = date(2026, 11, 5)
    overdue = {i.invoice_number for i in invoices if i.is_overdue(today)}
    assert overdue == EXPECTED_OVERDUE


def test_drafts_and_paid_never_overdue(invoices):
    far_future = date(2030, 1, 1)
    for inv in invoices:
        if inv.status in ("draft", "paid"):
            assert not inv.is_overdue(far_future)


def test_source_amounts_consistent(invoices):
    for inv in invoices:
        assert inv.total_minor == inv.subtotal_minor - inv.discount_minor + inv.tax_minor
        assert inv.balance_minor == inv.total_minor - inv.amount_paid_minor
