from datetime import date

import pytest

from app.services.csv_parser import StatementParseError, decode_upload, parse_amount, parse_date, parse_statement

HEADER = "txn_date,narration,reference,credit,debit,currency\n"


def test_parses_sample(raw_data):
    from tests.conftest import DATA

    rows = parse_statement((DATA / "bank_statement_sample.csv").read_text())
    assert len(rows) == 14
    credits = [r for r in rows if r.direction == "credit"]
    assert len(credits) == 12
    thornfield = next(r for r in rows if "THORNFIELD" in r.narration)
    assert thornfield.amount_minor == 735050 and thornfield.currency == "GBP"
    interest = rows[-1]
    assert interest.reference == "" and interest.amount_minor == 43122


@pytest.mark.parametrize(
    "text,expected",
    [("2,36,000.00", 23600000), ("236000", 23600000), ("₹ 1,18,000", 11800000), ("7350.5", 735050), ("", None)],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize("bad", ["-100", "(100)", "12.345", "abc", "1.2.3"])
def test_parse_amount_rejects(bad):
    with pytest.raises(ValueError):
        parse_amount(bad)


@pytest.mark.parametrize(
    "text", ["2026-09-05", "05-09-2026", "05/09/2026", "05.09.2026", "05-Sep-2026", "05 Sep 2026", "2026/09/05"]
)
def test_parse_date_formats_day_first(text):
    assert parse_date(text) == date(2026, 9, 5)


def test_bom_blank_lines_whitespace_and_aliases():
    text = "﻿\n\n Date , Description ,Ref,Credit,Debit, Currency \n\n 05/09/2026 ,  IMPS/KESTREL   FOODS ,x1, \"59,000.00\" ,,inr \n\n"
    rows = parse_statement(text)
    assert len(rows) == 1
    r = rows[0]
    assert r.narration == "IMPS/KESTREL FOODS" and r.amount_minor == 5900000 and r.currency == "INR"


def test_rejects_missing_columns():
    with pytest.raises(StatementParseError, match="missing required"):
        parse_statement("date,amount\n2026-01-01,5\n")


def test_rejects_bad_rows_with_line_numbers():
    text = HEADER + "2026-09-05,A,1,100,,INR\nnot-a-date,B,2,100,,INR\n2026-09-05,C,3,100,50,INR\n2026-09-05,D,4,,,INR\n"
    with pytest.raises(StatementParseError) as exc:
        parse_statement(text)
    errs = exc.value.errors
    assert any("line 3" in e for e in errs) and any("line 4" in e for e in errs) and any("line 5" in e for e in errs)


def test_rejects_unknown_currency_and_empty():
    with pytest.raises(StatementParseError):
        parse_statement(HEADER + "2026-09-05,A,1,100,,JPY\n")
    with pytest.raises(StatementParseError):
        parse_statement(HEADER)
    with pytest.raises(StatementParseError):
        parse_statement("")


def test_binary_rejected():
    with pytest.raises(StatementParseError):
        decode_upload(b"\x00\x01PK\x03\x04")
