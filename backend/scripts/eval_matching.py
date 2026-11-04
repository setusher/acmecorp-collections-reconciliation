"""Evaluate the matching engine on the sample statement plus synthetic tricky cases.

Run from backend/:  .venv/bin/python -m scripts.eval_matching  [--verbose]

Metrics (per credit row):
  precision = correct suggestions / all suggestions          (wrong matches hurt this)
  recall    = correct suggestions / rows that have an answer  (missed matches hurt this)
  wrong     = suggestions pointing at the wrong invoice(s)    (target: 0)
A row whose expected answer is "no match" counts as correct when nothing is suggested.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.core.money import to_minor
from app.models.domain import Customer, Invoice
from app.services.csv_parser import parse_statement
from app.services.matching.engine import MatchingEngine, Txn

DATA = Path(__file__).resolve().parents[2] / "data"


@dataclass
class Case:
    txn_date: str
    narration: str
    amount: str
    currency: str
    expected: list[str]  # [] = no match expected
    note: str
    max_band: str | None = None  # e.g. "medium" when the case is inherently ambiguous


# Ground truth for data/bank_statement_sample.csv (credit rows, in file order).
SAMPLE_EXPECTED = [
    (["INV-1004"], "number + payer + exact; INV-1005 has the same amount"),
    (["INV-1013"], "declared part payment; INV-1014 issued after the payment"),
    (["INV-1007"], "TDS: 3,54,000 - 10% of 3,00,000"),
    (["INV-1024"], "bare 'RE 1024'; INV-1025 same amount but issued later"),
    (["INV-1021"], "INV1021 without dash"),
    (["INV-1002"], "INV-1002 with dash"),
    (["INV-1016"], "singular CLINIC; Kestrel also has 59,000 invoices"),
    (["INV-1026"], "GBP decimal amount"),
    (["INV-1010", "INV-1011", "INV-1012"], "one payment for three invoices"),
    ([], "third party 'R K SHARMA', amount equals INV-1017: must not force"),
    ([], "unknown payer 'MAPLE RETAIL SERVICES'"),
    ([], "bank interest"),
]

SYNTHETIC = [
    Case("2026-10-22", "NEFT CR-KESTRAL FODS INV-1005", "59000", "INR", ["INV-1005"], "typos in payer"),
    Case("2026-10-15", "NEFT CR-BRIGHTLN LOGIST", "236000", "INR", ["INV-1002"], "truncated payer"),
    Case("2026-10-28", "RTGS/TECHNOLOGIES QUILLON/QT-0107", "177000", "INR", ["INV-1008"], "reordered + PO"),
    Case("2026-10-20", "NEFT CR SAFFRON PEAK HOSPITALITY INV 1010", "75600", "INR", ["INV-1010"], "TDS with number"),
    Case("2026-10-25", "NEFT CR-KESTREL FOODS", "59000", "INR", ["INV-1004"], "two equal invoices: oldest",
         max_band="medium"),
    Case("2026-10-30", "SEPA CR NORDLYS RETAIL", "9200", "EUR", ["INV-1024"], "two equal EUR invoices",
         max_band="medium"),
    Case("2026-10-20", "SWIFT CR HARBOUR ANALYTICS INC INV1022", "4800", "EUR", [], "wrong currency"),
    Case("2026-10-20", "NEFT CR THORNFIELD MEDIA", "7350.50", "INR", [], "GBP customer paying in INR"),
    Case("2026-10-20", "NEFT CR-ACME TRADERS", "59000", "INR", [], "unknown payer, common amount"),
    Case("2026-10-01", "NEFT CR-ORBIS PACKAGING", "472000", "INR", ["INV-1013"], "no number, exact amount"),
    Case("2026-10-01", "NEFT CR BRIGHTLINE LOGISTICS", "94400", "INR", [], "paid before invoice date"),
    Case("2026-10-01", "NEFT CR BRIGHTLINE INV-1001", "118000", "INR", [], "names an already paid invoice"),
    Case("2026-10-20", "NEFT CR-SAFFRON PEAK INV 1010/1011", "123900", "INR", ["INV-1010", "INV-1011"],
         "two numbers, one payment"),
    Case("2026-10-20", "NEFT CR-REDWOOD CLINICS", "100000", "INR", [], "amount fits nothing"),
    Case("2026-10-30", "UPI/HARBOURANALYTICS/HA2260", "4800", "USD", ["INV-1022"], "glued name + PO"),
    Case("2026-10-20", "SWIFT CR HARBOUR ANALYTICS", "2000", "USD", ["INV-1023"], "repeat instalment",
         max_band="medium"),
    Case("2026-11-03", "neft cr thornfield media inv/1027", "22800", "GBP", ["INV-1027"], "lowercase, INV/"),
    Case("2026-10-12", "NEFT CR-REDWOOD", "59000", "INR", ["INV-1016"], "short name, shared amount"),
    Case("2026-10-25", "IMPS/MR PRAKASH/INV-1017", "88500", "INR", ["INV-1017"], "third party quoting number"),
    Case("2026-10-20", "SWIFT CR HARBOUR ANALYTICS INV1021", "12475", "USD", ["INV-1021"],
         "bank fee shortfall stays partial", max_band="medium"),
    Case("2026-10-31", "SB INT CREDIT Q3", "1250.75", "INR", [], "interest"),
    Case("2026-10-20", "NEFT CR-MAPLE RETAIL", "9200", "INR", [], "generic word overlap, foreign amount"),
    Case("2026-10-20", "NEFT CR-QUILLON TECH", "531000", "INR", ["INV-1007", "INV-1008"], "two invoices summed"),
    Case("2026-10-20", "NEFT CR-ORBIS PKG", "100000", "INR", ["INV-1013"], "undeclared partial",
         max_band="low"),
    Case("2026-10-21", "NEFT CR-KESTREL FOODS INV-1016", "59000", "INR", [], "number belongs to another customer"),
]

BAND_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}


def load_engine() -> MatchingEngine:
    customers = [Customer(**c) for c in json.loads((DATA / "customers.json").read_text())]
    invoices = [Invoice.from_source(r) for r in json.loads((DATA / "invoices.json").read_text())]
    return MatchingEngine(customers, invoices)


def evaluate(verbose: bool = False) -> dict:
    engine = load_engine()
    rows = [r for r in parse_statement((DATA / "bank_statement_sample.csv").read_text()) if r.direction == "credit"]
    cases: list[tuple[Txn, list[str], str, str | None]] = []
    for r, (exp, note) in zip(rows, SAMPLE_EXPECTED, strict=True):
        cases.append((Txn(r.txn_date, r.narration, r.amount_minor, r.currency), exp, "sample: " + note, None))
    for c in SYNTHETIC:
        cases.append((Txn(date.fromisoformat(c.txn_date), c.narration, to_minor(c.amount), c.currency),
                      c.expected, "synthetic: " + c.note, c.max_band))

    suggested = correct_suggested = wrong = missed = with_answer = correct_nomatch = band_violations = 0
    lines = []
    for txn, expected, note, max_band in cases:
        res = engine.match(txn)
        got = sorted(a.invoice_number for a in res.allocations) if res.status == "suggested" else []
        exp = sorted(expected)
        if exp:
            with_answer += 1
        if got:
            suggested += 1
            if got == exp:
                correct_suggested += 1
            else:
                wrong += 1
        elif exp:
            missed += 1
        else:
            correct_nomatch += 1
        if max_band and BAND_ORDER[res.band] > BAND_ORDER[max_band]:
            band_violations += 1
        ok = got == exp and not (max_band and BAND_ORDER[res.band] > BAND_ORDER[max_band])
        lines.append(f"{'OK ' if ok else 'BAD'} {res.score:3d} {res.band:6s} got={','.join(got) or '-':26s} "
                     f"exp={','.join(exp) or '-':26s} {note}")
        if verbose:
            lines.append(f"        {txn.narration!r} -> {res.reason}")
    precision = correct_suggested / suggested if suggested else 1.0
    recall = correct_suggested / with_answer if with_answer else 1.0
    summary = {
        "cases": len(cases), "suggested": suggested, "correct_suggested": correct_suggested, "wrong": wrong,
        "missed": missed, "correct_no_match": correct_nomatch, "band_violations": band_violations,
        "precision": round(precision, 3), "recall": round(recall, 3),
    }
    return {"lines": lines, "summary": summary}


def main() -> int:
    out = evaluate(verbose="--verbose" in sys.argv or "-v" in sys.argv)
    print("\n".join(out["lines"]))
    print()
    for k, v in out["summary"].items():
        print(f"{k:18s} {v}")
    return 0 if out["summary"]["wrong"] == 0 and out["summary"]["band_violations"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
