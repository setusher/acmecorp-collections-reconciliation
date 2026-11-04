"""Narration normalisation and evidence extraction (pure functions)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Transfer rails, direction markers and banking noise that never identify a payer.
TRANSFER_NOISE = {
    "NEFT", "RTGS", "IMPS", "UPI", "SWIFT", "SEPA", "ACH", "NACH", "ECS", "CR", "DR", "TRF", "TRANSFER",
    "FT", "INB", "MOB", "NET", "NETBANKING", "BANKING", "REF", "REFNO", "UTR", "TXN", "TRN", "CHQ",
    "CHEQUE", "CLG", "INWARD", "OUTWARD", "REMITTANCE", "REMIT", "CREDIT", "DEBIT", "BY", "FROM", "TO",
    "FOR", "AND", "OF", "THE", "AC", "ACCT", "ACCOUNT", "WIRE", "BANK", "NO", "RE", "INV", "INVOICE",
    "INVOICES", "BILL", "BILLS", "PAYMENT", "PAYMENTS", "PAYMT", "PMT", "PYMT", "DUES", "DUE", "PART",
    "PARTIAL", "ADVANCE", "INSTALMENT", "INSTALLMENT", "BALANCE", "AMOUNT", "AMT", "TOWARDS", "AGAINST",
    "SETTLEMENT", "FULL", "FINAL", "ON", "OUR", "YOUR", "VIA", "PAID", "PAY",
}
MONTHS = {
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "SEPT", "OCT", "NOV", "DEC",
    "JANUARY", "FEBRUARY", "MARCH", "APRIL", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER",
    "NOVEMBER", "DECEMBER",
}
COMPANY_SUFFIXES = {
    "PVT", "PRIVATE", "PRIV", "LTD", "LIMITED", "LLP", "LLC", "INC", "INCORPORATED", "GMBH", "AG", "CO",
    "CORP", "CORPORATION", "COMPANY", "PLC", "SA", "SARL", "BV", "NV", "PTE", "PTY", "LTDA", "SRL", "OPC",
}
# Words that describe a line of business. They are shared across many companies,
# so they are weak evidence on their own (e.g. "MAPLE RETAIL" vs "Nordlys Retail").
GENERIC_BUSINESS_WORDS = {
    "LOGISTICS", "FOODS", "FOOD", "TECHNOLOGIES", "TECHNOLOGY", "TECH", "HOSPITALITY", "PACKAGING",
    "CLINICS", "CLINIC", "ANALYTICS", "RETAIL", "MEDIA", "SERVICES", "SERVICE", "SOLUTIONS", "SYSTEMS",
    "INDUSTRIES", "ENTERPRISES", "TRADING", "TRADERS", "GROUP", "HOLDINGS", "INTERNATIONAL", "GLOBAL",
    "INDIA", "CONSULTING", "SOFTWARE", "DIGITAL", "LABS", "HEALTH", "HEALTHCARE", "HOSPITAL", "MOTORS",
    "EXPORTS", "IMPORTS", "PHARMA", "PHARMACEUTICALS", "VENTURES", "PARTNERS", "ASSOCIATES", "AGENCY",
    "STUDIO", "STUDIOS", "NETWORKS", "INFOTECH", "INFRA", "FINANCE", "CAPITAL", "MARKETING", "HOTELS",
}
PARTIAL_HINTS = {"PART", "PARTIAL", "ADVANCE", "INSTALMENT", "INSTALLMENT", "ONACCOUNT"}
BANK_ENTRY_PATTERNS = [
    re.compile(p)
    for p in (
        r"^INT[\s.]*PD\b", r"\bINTEREST\b", r"^INT[\s.]*(CR|CREDIT)\b", r"\bSB\s*INT\b", r"\bCASHBACK\b",
        r"\bREVERSAL\b", r"\bREFUND\b", r"\bCHARGES?\b.*\bREV", r"\bSWEEP\b", r"\bFD\b.*\b(MAT|CLOS)",
    )
]

# INV-1002, INV 1002, INV1002, INV/1002, inv#1002, INVOICE NO. 1002; plus lists "INV 1010/1011 & 1012".
_INV_RE = re.compile(
    r"\bINV(?:OICE)?(?:\s*NO)?[\s\-/#:.]*0*(\d{3,6})((?:\s*[,/&+]\s*(?:INV[\s\-/#:.]*)?0*\d{3,6}\b)*)"
)
_LIST_NUM_RE = re.compile(r"\d{3,6}")
_BARE_NUM_RE = re.compile(r"(?<![A-Z0-9])(\d{3,6})(?![A-Z0-9])")


@dataclass
class NarrationFeatures:
    raw: str
    upper: str
    payer_tokens: list[str]
    invoice_numbers: list[int] = field(default_factory=list)  # explicit INV-xxxx references
    bare_numbers: list[int] = field(default_factory=list)  # standalone 3-6 digit tokens (weak)
    partial_hint: bool = False
    bank_entry: bool = False

    @property
    def payer_text(self) -> str:
        return " ".join(self.payer_tokens)


def tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"[^A-Z0-9]+", text.upper()) if t]


def name_tokens(name: str) -> list[str]:
    """Tokens of a company name with legal suffixes removed (``Kestrel Foods Private Limited`` -> KESTREL FOODS)."""
    return [t for t in tokenize(name) if t not in COMPANY_SUFFIXES and not t.isdigit()]


def extract_invoice_numbers(upper: str) -> list[int]:
    found: list[int] = []
    for m in _INV_RE.finditer(upper):
        nums = [int(m.group(1))] + [int(x) for x in _LIST_NUM_RE.findall(m.group(2) or "")]
        for n in nums:
            if n not in found:
                found.append(n)
    return found


def extract_features(narration: str) -> NarrationFeatures:
    upper = " ".join(narration.upper().split())
    inv_numbers = extract_invoice_numbers(upper)
    without_inv = _INV_RE.sub(" ", upper)
    bare = [int(x) for x in _BARE_NUM_RE.findall(without_inv) if int(x) not in inv_numbers]
    tokens = tokenize(upper)
    joined = " ".join(tokens)
    partial_hint = any(t in PARTIAL_HINTS for t in tokens) or "ON ACCOUNT" in joined
    payer_tokens = [
        t
        for t in tokens
        if t not in TRANSFER_NOISE
        and t not in MONTHS
        and t not in COMPANY_SUFFIXES
        and len(t) > 1  # initials like "R K" carry no company signal
        and not any(ch.isdigit() for ch in t)  # references, dates, amounts
    ]
    bank_entry = any(p.search(upper) for p in BANK_ENTRY_PATTERNS)
    return NarrationFeatures(
        raw=narration,
        upper=upper,
        payer_tokens=payer_tokens,
        invoice_numbers=inv_numbers,
        bare_numbers=bare,
        partial_hint=partial_hint,
        bank_entry=bank_entry,
    )


def invoice_numeric(invoice_number: str) -> int | None:
    m = re.search(r"(\d+)$", invoice_number)
    return int(m.group(1)) if m else None
