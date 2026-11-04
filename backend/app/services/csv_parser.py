"""Robust parser for bank statement CSVs.

Expected columns (case/whitespace-insensitive, a few common aliases accepted):
``txn_date, narration, reference, credit, debit, currency``.

Handles: UTF-8 BOM, blank lines, surrounding whitespace, Indian digit grouping
(``2,36,000.00``), currency symbols, several date formats (ISO first, then
day-first forms because this is an Indian bank statement).  Any malformed row
rejects the whole file with row-numbered errors: a half-imported statement is
worse than none.
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from app.core.money import SUPPORTED_CURRENCIES, to_minor

REQUIRED = ("txn_date", "narration", "reference", "credit", "debit", "currency")
HEADER_ALIASES = {
    "date": "txn_date", "transaction_date": "txn_date", "value_date": "txn_date", "txn date": "txn_date",
    "description": "narration", "particulars": "narration", "details": "narration",
    "ref": "reference", "ref_no": "reference", "reference_no": "reference", "cheque/ref no": "reference",
    "deposit": "credit", "credit_amount": "credit", "cr": "credit",
    "withdrawal": "debit", "debit_amount": "debit", "dr": "debit",
    "ccy": "currency",
}
DATE_FORMATS = (
    "%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%y", "%d/%m/%y",
    "%d-%b-%Y", "%d %b %Y", "%d-%b-%y", "%d %B %Y", "%b %d, %Y", "%Y%m%d",
)
_AMOUNT_CLEAN = re.compile(r"[\s,₹$€£]|INR|USD|EUR|GBP", re.IGNORECASE)
_AMOUNT_OK = re.compile(r"^\d+(\.\d{1,2})?$")
MAX_NARRATION = 500


class StatementParseError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors[:10]))
        self.errors = errors


@dataclass(frozen=True)
class ParsedRow:
    row_no: int  # 1-based line number in the file (header = 1)
    txn_date: date
    narration: str
    reference: str
    amount_minor: int
    direction: Literal["credit", "debit"]
    currency: str


def parse_date(text: str) -> date:
    text = text.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {text!r}")


def parse_amount(text: str) -> int | None:
    """Return minor units, ``None`` for blank. Raises on negative/garbage."""
    raw = (text or "").strip()
    if not raw or raw in {"-", "--"}:
        return None
    cleaned = _AMOUNT_CLEAN.sub("", raw)
    if cleaned.startswith(("(", "-")):
        raise ValueError(f"negative amount {raw!r}")
    if not _AMOUNT_OK.match(cleaned):
        raise ValueError(f"invalid amount {raw!r}")
    try:
        return to_minor(Decimal(cleaned))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid amount {raw!r}") from exc


def _normalise_header(name: str) -> str:
    key = name.replace("﻿", "").strip().lower()
    key = HEADER_ALIASES.get(key, key)
    return key.replace(" ", "_")


def decode_upload(data: bytes) -> str:
    if b"\x00" in data[:4096]:
        raise StatementParseError(["file looks binary, expected a CSV text file"])
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise StatementParseError(["file is not valid UTF-8 text"])


def parse_statement(text: str, max_rows: int = 5000) -> list[ParsedRow]:
    text = text.lstrip("﻿")
    lines = text.splitlines()
    # Skip leading blank lines so the header is the first non-empty line.
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        raise StatementParseError(["file is empty"])
    reader = csv.reader(io.StringIO("\n".join(lines)), skipinitialspace=True)
    try:
        header = next(reader)
    except (StopIteration, csv.Error) as exc:
        raise StatementParseError([f"could not read header: {exc}"]) from exc
    cols = [_normalise_header(h) for h in header]
    missing = [c for c in REQUIRED if c not in cols]
    if missing:
        raise StatementParseError([f"missing required column(s): {', '.join(missing)}"])
    idx = {c: cols.index(c) for c in REQUIRED}

    rows: list[ParsedRow] = []
    errors: list[str] = []
    try:
        for line_no, rec in enumerate(reader, start=2):
            if not rec or all(not cell.strip() for cell in rec):
                continue  # blank line
            if len(rec) < len(header):
                rec = rec + [""] * (len(header) - len(rec))
            def get(c: str, rec: list[str] = rec) -> str:
                return rec[idx[c]].strip()
            try:
                txn_date = parse_date(get("txn_date"))
                narration = " ".join(get("narration").split())
                if not narration:
                    raise ValueError("narration is empty")
                if len(narration) > MAX_NARRATION:
                    raise ValueError("narration too long")
                currency = get("currency").upper()
                if currency not in SUPPORTED_CURRENCIES:
                    raise ValueError(f"unsupported currency {currency!r}")
                credit, debit = parse_amount(get("credit")), parse_amount(get("debit"))
                if credit is not None and debit is not None and credit and debit:
                    raise ValueError("both credit and debit are filled")
                if credit:
                    amount, direction = credit, "credit"
                elif debit:
                    amount, direction = debit, "debit"
                else:
                    raise ValueError("no credit or debit amount")
                rows.append(
                    ParsedRow(line_no, txn_date, narration, get("reference")[:100], amount, direction, currency)
                )
            except ValueError as exc:
                errors.append(f"line {line_no}: {exc}")
            if len(rows) > max_rows:
                raise StatementParseError([f"too many rows (max {max_rows})"])
    except csv.Error as exc:
        errors.append(f"CSV syntax error: {exc}")
    if errors:
        raise StatementParseError(errors)
    if not rows:
        raise StatementParseError(["no transactions found"])
    return rows
