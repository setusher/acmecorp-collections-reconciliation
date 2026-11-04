"""Transaction -> invoice suggestion engine (pure, deterministic, no LLM).

Score = payer points + amount points + invoice-number points + date points
        - penalties, clamped to 0..99.

  payer (identified)      up to 45 (45 x ensemble score)
  payer (weak hint)       up to 10
  amount                  0..40 (see signals.AMOUNT_POINTS)
  invoice number          +25 explicit (INV-1004), +15 bare (RE 1024)
  PO number               +20 if the invoice's PO appears in the narration
  date                    +5 (up to 90 days late) / +2 / -3, and -50 if paid before invoice date
  penalties               -10 narration names a different invoice,
                          -15 named invoice belongs to another customer,
                          -25 narration names only paid/draft/unknown invoices (possible duplicate),
                          -25 undeclared partial while another invoice of the payer matches exactly,
  conflict cap            payer and named invoice belong to different customers -> below threshold,
                          ambiguity (runner-up within 10 points): -(10 + (10 - gap))

Hard rules (never overridden): credit rows only; same currency; invoice must
be ``sent`` with balance > 0; a receipt larger than the balance is never
matched to a single invoice; without an identified payer or an explicit
invoice number a match on amount alone is capped below the threshold.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from itertools import combinations
from typing import Literal

from app.core.money import format_amount
from app.models.domain import Customer, Invoice
from app.services.matching.normalize import NarrationFeatures, extract_features, invoice_numeric
from app.services.matching.payer import PayerMatcher, PayerScore
from app.services.matching.signals import AMOUNT_POINTS, amount_signal, date_signal, tds_expected

PAYER_POINTS = 45
WEAK_PAYER_POINTS = 10
INV_EXPLICIT_POINTS = 25
INV_BARE_POINTS = 15
OTHER_INVOICE_NAMED_PENALTY = 10
CROSS_CUSTOMER_PENALTY = 15
AMOUNT_ONLY_CAP = 35
PO_POINTS = 20
NAMED_NOT_OPEN_PENALTY = 25
PARTIAL_CAP = 80  # a receipt that does not settle the invoice is never "high"
EXACT_ELSEWHERE_PENALTY = 25  # partial here, but another invoice of the payer matches exactly
CONFLICT_CAP = 35  # payer and named invoice disagree -> always a human decision
AMBIGUITY_GAP = 10
GROUP_POINTS = 33
GROUP_MAX_SIZE = 5
GROUP_MAX_OPEN = 15

THRESHOLD_NO_MATCH = 40
BAND_HIGH = 85
BAND_MEDIUM = 65

Band = Literal["high", "medium", "low", "none"]


def band_for(score: int) -> Band:
    if score >= BAND_HIGH:
        return "high"
    if score >= BAND_MEDIUM:
        return "medium"
    if score >= THRESHOLD_NO_MATCH:
        return "low"
    return "none"


@dataclass
class Txn:
    txn_date: date
    narration: str
    amount_minor: int
    currency: str
    direction: str = "credit"
    reference: str = ""


@dataclass
class Allocation:
    invoice_number: str
    customer_id: str
    amount_minor: int  # cash applied to the invoice
    tds_minor: int = 0  # TDS that would close the invoice if the approver chooses so


@dataclass
class Candidate:
    allocations: list[Allocation]
    customer_id: str
    raw: float
    reasons: list[str]
    kind: Literal["single", "group"]
    amount_kind: str
    sort_key: tuple = ()
    score: int = 0

    @property
    def label(self) -> str:
        return " + ".join(a.invoice_number for a in self.allocations)


@dataclass
class MatchResult:
    status: Literal["suggested", "no_match", "ignored"]
    score: int
    band: Band
    reason: str
    allocations: list[Allocation] = field(default_factory=list)
    customer_id: str | None = None
    amount_kind: str | None = None
    alternatives: list[dict] = field(default_factory=list)
    payer: dict | None = None
    signals: dict = field(default_factory=dict)


def _compact(text: str) -> str:
    return "".join(ch for ch in text.upper() if ch.isalnum())


def _po_in(po: str | None, f: NarrationFeatures) -> bool:
    if not po:
        return False
    cpo = _compact(po)
    return len(cpo) >= 4 and cpo in _compact(f.upper)


class MatchingEngine:
    def __init__(self, customers: list[Customer], invoices: list[Invoice]):
        self.customers = {c.customer_id: c for c in customers}
        self.invoices = invoices
        self.by_numeric: dict[int, Invoice] = {}
        for inv in invoices:
            n = invoice_numeric(inv.invoice_number)
            if n is not None:
                self.by_numeric[n] = inv
        self.payers = PayerMatcher(customers)

    # ------------------------------------------------------------------ helpers
    def _open(self, currency: str, customer_id: str | None = None) -> list[Invoice]:
        return [
            i for i in self.invoices
            if i.is_open() and i.currency == currency and (customer_id is None or i.customer_id == customer_id)
        ]

    def _payer_points(self, inv: Invoice, payer: PayerScore | None, scores: dict[str, PayerScore]):
        if payer and inv.customer_id == payer.customer_id:
            return PAYER_POINTS * payer.score, f"payer name {round(payer.score * 100)}% match"
        hint = scores.get(inv.customer_id)
        if payer is None and hint and hint.score >= 0.3:
            return WEAK_PAYER_POINTS * hint.score, None
        return 0.0, None

    # ------------------------------------------------------------- single match
    def _score_single(self, txn: Txn, inv: Invoice, f: NarrationFeatures, payer: PayerScore | None,
                      scores: dict[str, PayerScore], named: list[Invoice], named_not_open: bool) -> Candidate | None:
        amt = amount_signal(txn.amount_minor, inv, f.partial_hint)
        if amt.kind in ("over", "total"):
            return None  # cannot apply a larger receipt to this invoice alone
        reasons: list[str] = []
        raw = 0.0
        num = invoice_numeric(inv.invoice_number)
        explicit = num in f.invoice_numbers
        bare = (not explicit) and num in f.bare_numbers and payer is not None and inv.customer_id == payer.customer_id
        if explicit:
            raw += INV_EXPLICIT_POINTS
            reasons.append(f"{inv.invoice_number} named in narration")
        elif bare:
            raw += INV_BARE_POINTS
            reasons.append(f"number {num} in narration matches {inv.invoice_number}")
        po_hit = _po_in(inv.po_number, f)
        if po_hit:
            raw += PO_POINTS
            reasons.append(f"PO {inv.po_number} in narration")
        pp, ptext = self._payer_points(inv, payer, scores)
        raw += pp
        if ptext:
            reasons.append(ptext)
        raw += amt.points
        reasons.append(amt.text)
        ds = date_signal(txn.txn_date, inv)
        raw += ds.points
        if ds.text:
            reasons.append(ds.text)
        if named and not explicit:
            raw -= OTHER_INVOICE_NAMED_PENALTY
            reasons.append(f"narration names {', '.join(n.invoice_number for n in named)} instead")
        if explicit and payer and inv.customer_id != payer.customer_id:
            raw -= CROSS_CUSTOMER_PENALTY
            reasons.append(f"{inv.invoice_number} belongs to {inv.customer_name}, but payer looks like {payer.name}")
        if named_not_open:
            raw -= NAMED_NOT_OPEN_PENALTY
        if amt.kind in ("partial", "partial_declared", "instalment"):
            raw = min(raw, PARTIAL_CAP)
        if payer is None and not (explicit or po_hit):
            if amt.kind not in ("balance", "tds", "instalment"):
                return None  # unknown payer + inexact amount is noise, not a lead
            raw = min(raw, AMOUNT_ONLY_CAP)
            reasons.append("payer not recognised")
        alloc = Allocation(inv.invoice_number, inv.customer_id, txn.amount_minor, amt.tds_minor)
        return Candidate([alloc], inv.customer_id, raw, reasons, "single", amt.kind,
                         sort_key=(inv.due_date, inv.invoice_number))

    # -------------------------------------------------------------- group match
    def _group_candidates(self, txn: Txn, f: NarrationFeatures, payer: PayerScore) -> list[Candidate]:
        pool = [i for i in self._open(txn.currency, payer.customer_id) if i.invoice_date <= txn.txn_date]
        if len(pool) < 2 or len(pool) > GROUP_MAX_OPEN:
            return []
        out: list[Candidate] = []
        for size in range(2, min(GROUP_MAX_SIZE, len(pool)) + 1):
            for combo in combinations(pool, size):
                with_tds = all(tds_expected(i) for i in combo)
                variants = [(False, sum(i.balance_minor for i in combo))]
                if with_tds:
                    variants.append((True, sum(i.balance_minor - tds_expected(i) for i in combo)))
                for use_tds, total in variants:
                    if total != txn.amount_minor:
                        continue
                    allocs = [
                        Allocation(i.invoice_number, i.customer_id,
                                   i.balance_minor - (tds_expected(i) if use_tds else 0),
                                   tds_expected(i) if use_tds else 0)
                        for i in combo
                    ]
                    nums = {invoice_numeric(i.invoice_number) for i in combo}
                    raw = PAYER_POINTS * payer.score + GROUP_POINTS + 5
                    reasons = [f"payer name {round(payer.score * 100)}% match",
                               f"amount equals the sum of {size} open invoices"
                               + (" less 10% TDS each" if use_tds else "")]
                    if f.invoice_numbers and set(f.invoice_numbers) <= nums:
                        raw += INV_EXPLICIT_POINTS
                        reasons.insert(0, "invoice numbers named in narration")
                    elif f.invoice_numbers:
                        raw -= OTHER_INVOICE_NAMED_PENALTY
                    out.append(Candidate(allocs, payer.customer_id, raw, reasons, "group",
                                         "group_tds" if use_tds else "group",
                                         sort_key=(max(i.due_date for i in combo), size)))
        return out

    # --------------------------------------------------------------------- main
    def match(self, txn: Txn) -> MatchResult:
        if txn.direction != "credit":
            return MatchResult("ignored", 0, "none", "Debit (money out): not reconciled against invoices")
        f = extract_features(txn.narration)
        score_list = self.payers.score_all(f.payer_tokens)
        scores = {s.customer_id: s for s in score_list}
        payer = PayerMatcher.identify(score_list)
        signals: dict = {
            "payer_tokens": f.payer_tokens,
            "invoice_numbers": [f"INV-{n}" for n in f.invoice_numbers],
            "bare_numbers": f.bare_numbers,
            "partial_hint": f.partial_hint,
            "payer_scores": [
                {"customer_id": s.customer_id, "score": s.score, "anchored": s.anchored, "components": s.components}
                for s in score_list[:3]
            ],
        }
        payer_info = {"customer_id": payer.customer_id, "name": payer.name, "score": payer.score} if payer else None

        named = [self.by_numeric[n] for n in f.invoice_numbers if n in self.by_numeric]
        notes: list[str] = []
        for inv in named:
            if inv.status == "paid" or (inv.status == "sent" and inv.balance_minor == 0):
                notes.append(f"{inv.invoice_number} named but already paid")
            elif inv.status == "draft":
                notes.append(f"{inv.invoice_number} named but is a draft (not billed)")
            elif inv.currency != txn.currency:
                notes.append(f"{inv.invoice_number} named but is billed in {inv.currency}, receipt is {txn.currency}")
        for n in f.invoice_numbers:
            if n not in self.by_numeric:
                notes.append(f"INV-{n} named but no such invoice")

        if f.bank_entry and payer is None and not named:
            return MatchResult("no_match", 0, "none", "Bank entry (interest/reversal), not a customer receipt",
                               signals=signals)

        if payer and self.customers[payer.customer_id].currency != txn.currency:
            notes.append(f"{payer.name} is billed in {self.customers[payer.customer_id].currency}, "
                         f"receipt is {txn.currency}")

        # Candidate pool: identified payer's open invoices + explicitly named open invoices,
        # or (no payer) every open invoice in the currency, amount-capped below threshold.
        pool: dict[str, Invoice] = {}
        if payer:
            pool.update({i.invoice_number: i for i in self._open(txn.currency, payer.customer_id)})
        else:
            pool.update({i.invoice_number: i for i in self._open(txn.currency)})
        for inv in named:
            if inv.is_open() and inv.currency == txn.currency:
                pool[inv.invoice_number] = inv
        open_named = [i for i in named if i.is_open() and i.currency == txn.currency]

        named_not_open = bool(f.invoice_numbers) and not open_named
        cands = [
            c for inv in pool.values()
            if (c := self._score_single(txn, inv, f, payer, scores, open_named, named_not_open))
        ]
        if payer:
            cands += self._group_candidates(txn, f, payer)

        if not cands:
            why = notes or [
                f"Payer {payer.name} recognised but no open {txn.currency} invoice fits {format_amount(txn.amount_minor, txn.currency)}"
                if payer else "Payer not recognised and no invoice fits"
            ]
            return MatchResult("no_match", 0, "none", "; ".join(why), payer=payer_info, signals=signals)

        # A partial is suspect when the amount exactly equals another invoice of the payer
        # (e.g. an advance for an invoice not yet issued at the payment date).
        exact_other = [c for c in cands if c.kind == "single" and c.amount_kind in ("balance", "tds")]
        for c in cands:
            if c.amount_kind == "partial" and exact_other:
                c.raw -= EXACT_ELSEWHERE_PENALTY
                c.reasons.append(f"amount exactly equals {exact_other[0].label}")
        conflict = payer is not None and any(i.customer_id != payer.customer_id for i in open_named)
        if conflict:
            other = next(i for i in open_named if i.customer_id != payer.customer_id)
            for c in cands:
                c.raw = min(c.raw, CONFLICT_CAP)
            notes.append(f"conflict: payer looks like {payer.name} but narration names {other.invoice_number} "
                         f"of {other.customer_name}")

        cands.sort(key=lambda c: (-c.raw, c.sort_key))
        top = cands[0]
        ambiguity = None
        if len(cands) > 1:
            gap = top.raw - cands[1].raw
            if gap < AMBIGUITY_GAP:
                penalty = AMBIGUITY_GAP + (AMBIGUITY_GAP - gap)
                top.raw -= penalty
                ambiguity = (f"ambiguous: {cands[1].label} fits almost as well"
                             + (" (suggested the oldest due)" if gap == 0 else ""))
        for c in cands:
            c.score = int(max(0, min(99, round(c.raw))))
        alternatives = [
            {"invoice_numbers": [a.invoice_number for a in c.allocations], "score": c.score,
             "reason": "; ".join(c.reasons), "kind": c.kind}
            for c in cands[1:4]
        ]
        reason_parts = top.reasons + ([ambiguity] if ambiguity else []) + notes
        reason = "; ".join(reason_parts)
        reason = reason[0].upper() + reason[1:]
        signals["ambiguous"] = bool(ambiguity)
        if top.score < THRESHOLD_NO_MATCH:
            alternatives = [
                {"invoice_numbers": [a.invoice_number for a in c.allocations], "score": c.score,
                 "reason": "; ".join(c.reasons), "kind": c.kind}
                for c in cands[:3]
            ]
            return MatchResult("no_match", top.score, "none", f"No confident match. Possible lead: {top.label} ({reason})",
                               payer=payer_info, alternatives=alternatives,
                               signals=signals)
        return MatchResult("suggested", top.score, band_for(top.score), reason, top.allocations, top.customer_id,
                           top.amount_kind, alternatives, payer_info, signals)

    def match_many(self, txns: list[Txn]) -> list[MatchResult]:
        """Match a statement; flag receipts that compete for the same invoice balance."""
        results = [self.match(t) for t in txns]
        claimed: dict[str, int] = {}
        for idx, res in enumerate(results):
            if res.status != "suggested":
                continue
            for a in res.allocations:
                inv = next(i for i in self.invoices if i.invoice_number == a.invoice_number)
                prior = claimed.get(a.invoice_number, 0)
                if prior + a.amount_minor + a.tds_minor > inv.balance_minor:
                    res.score = max(0, res.score - 20)
                    res.band = band_for(res.score)
                    res.reason += f"; {a.invoice_number} is also suggested for an earlier row"
                    if res.score < THRESHOLD_NO_MATCH:
                        res.status = "no_match"
                claimed[a.invoice_number] = prior + a.amount_minor + a.tds_minor
        return results
