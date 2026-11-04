"""Statement upload, suggestions, and human approval of payments."""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict

from app.core import clock
from app.core.money import format_amount, tds_minor
from app.repositories import Repos
from app.repositories.db import new_id
from app.services.csv_parser import StatementParseError, decode_upload, parse_statement
from app.services.matching.engine import MatchingEngine, PaymentHint, Txn

TDS_TOLERANCE_MINOR = 100  # ₹1 rounding tolerance when the customer rounds the TDS amount
ALLOWED_EXTENSIONS = (".csv",)
ALLOWED_TYPES = {"text/csv", "application/vnd.ms-excel", "text/plain", "application/csv", "application/octet-stream",
                 ""}


class ReconciliationError(ValueError):
    pass


class ConflictError(RuntimeError):
    pass


def fingerprint(row) -> str:
    key = f"{row.txn_date.isoformat()}|{row.amount_minor}|{row.currency}|{row.direction}|{row.reference}|" \
          f"{' '.join(row.narration.upper().split())}"
    return hashlib.sha256(key.encode()).hexdigest()


async def upload_statement(repos: Repos, filename: str, content_type: str, data: bytes, actor: str,
                           max_bytes: int, max_rows: int) -> dict:
    name = (filename or "").strip()
    if not name.lower().endswith(ALLOWED_EXTENSIONS):
        raise ReconciliationError("only .csv files are accepted")
    if (content_type or "").split(";")[0].strip().lower() not in ALLOWED_TYPES:
        raise ReconciliationError(f"unexpected content type {content_type!r}")
    if len(data) > max_bytes:
        raise ReconciliationError(f"file too large (max {max_bytes // 1024} KB)")
    if not data.strip():
        raise ReconciliationError("file is empty")
    sha = hashlib.sha256(data).hexdigest()
    existing = await repos.recon.find_statement_by_sha(sha)
    if existing:
        raise ConflictError(f"this exact file was already uploaded (statement {existing['_id']})")
    try:
        rows = parse_statement(decode_upload(data), max_rows=max_rows)
    except StatementParseError as exc:
        raise ReconciliationError("could not parse statement: " + "; ".join(exc.errors[:10])) from exc

    customers = await repos.master.list_customers()
    invoices = await repos.master.list_invoices()
    engine = MatchingEngine(customers, invoices, await payment_hints(repos))
    sid = new_id()
    fps = [fingerprint(r) for r in rows]
    already = await repos.recon.existing_fingerprints(fps)
    seen_in_file: set[str] = set()
    to_match = []
    tx_docs, now = [], clock.now()
    for r, fp in zip(rows, fps, strict=True):
        duplicate = fp in already or fp in seen_in_file
        seen_in_file.add(fp)
        tid = new_id()
        status = "ignored" if r.direction == "debit" else ("duplicate" if duplicate else "pending")
        tx_docs.append({
            "_id": tid, "statement_id": sid, "row_no": r.row_no, "txn_date": r.txn_date.isoformat(),
            "narration": r.narration, "reference": r.reference, "amount_minor": r.amount_minor,
            "direction": r.direction, "currency": r.currency, "status": status,
            # duplicates keep a unique fingerprint so the index holds; the original row stays authoritative
            "fingerprint": fp if not duplicate else f"{fp}:dup:{tid}", "created_at": now,
        })
        if status == "pending":
            to_match.append((tid, Txn(r.txn_date, r.narration, r.amount_minor, r.currency, r.direction,
                                      r.reference)))

    results = engine.match_many([t for _, t in to_match])
    sug_docs = []
    by_tid = {d["_id"]: d for d in tx_docs}
    for (tid, _), res in zip(to_match, results, strict=True):
        by_tid[tid]["status"] = "suggested" if res.status == "suggested" else "unmatched"
        sug_docs.append({
            "_id": new_id(), "statement_id": sid, "transaction_id": tid, "status": "pending",
            "match_status": res.status, "score": res.score, "band": res.band, "reason": res.reason,
            "allocations": [asdict(a) for a in res.allocations], "customer_id": res.customer_id,
            "amount_kind": res.amount_kind, "alternatives": res.alternatives, "payer": res.payer,
            "signals": res.signals, "created_at": now,
        })
    stmt = {
        "_id": sid, "filename": name[:200], "sha256": sha, "uploaded_at": now, "uploaded_by": actor,
        "row_count": len(rows), "credit_count": sum(1 for r in rows if r.direction == "credit"),
        "suggested_count": sum(1 for s in sug_docs if s["match_status"] == "suggested"),
        "duplicate_count": sum(1 for d in tx_docs if d["status"] == "duplicate"),
    }
    await repos.recon.insert_statement(stmt)
    await repos.recon.insert_transactions(tx_docs)
    await repos.recon.insert_suggestions(sug_docs)
    await repos.audit.log(actor, "statement_uploaded", f"statement:{sid}",
                          {"filename": stmt["filename"], "rows": len(rows), "suggested": stmt["suggested_count"]})
    return stmt


_REF_TOKEN = re.compile(r"\b[A-Z0-9][A-Z0-9/-]{5,24}\b")
_INV_TOKEN = re.compile(r"\bINV[\s\-/#:.]*0*(\d{3,6})\b", re.IGNORECASE)


def extract_hint(customer_id: str, text: str, said_on) -> PaymentHint | None:
    upper = text.upper()
    invoices = sorted({f"INV-{n}" for n in _INV_TOKEN.findall(upper)})
    without_inv = _INV_TOKEN.sub(" ", upper)
    refs = []
    for tok in _REF_TOKEN.findall(without_inv):
        compact = re.sub(r"[^A-Z0-9]", "", tok)
        if len(compact) >= 6 and sum(ch.isdigit() for ch in compact) >= 4:
            refs.append(compact)
    if not invoices and not refs:
        return None
    return PaymentHint(customer_id, refs, invoices, said_on, " ".join(text.split())[:300])


async def payment_hints(repos: Repos) -> list[PaymentHint]:
    """Collect "we have paid" claims from customer emails (category claims_paid)."""
    hints = []
    async for m in repos.db.messages.find({"direction": "in", "category": "claims_paid"}):
        conv = await repos.collections.get_conversation(m["conversation_id"])
        if not conv or not conv.get("customer_id"):
            continue
        received = m.get("received_at") or m.get("created_at")
        h = extract_hint(conv["customer_id"], m.get("clean_text") or m.get("body_text", ""),
                         received.date() if received else None)
        if h:
            hints.append(h)
    return hints


async def statement_detail(repos: Repos, sid: str) -> dict | None:
    stmt = await repos.recon.get_statement(sid)
    if stmt is None:
        return None
    sugs = {s["transaction_id"]: s for s in await repos.recon.suggestions_for(sid)}
    invoices = {i.invoice_number: i for i in await repos.master.list_invoices()}
    rows = []
    for t in await repos.recon.transactions_for(sid):
        s = sugs.get(t["_id"])
        if s:
            for a in s.get("allocations", []):
                inv = invoices.get(a["invoice_number"])
                if inv:
                    a["balance_minor"] = inv.balance_minor
                    a["status"] = inv.status
                    a["customer_name"] = inv.customer_name
                    a["total_minor"] = inv.total_minor
                    a["expected_tds_minor"] = tds_minor(inv.subtotal_minor) if inv.currency == "INR" else 0
        rows.append({"transaction": t, "suggestion": s})
    return {"statement": stmt, "rows": rows}


async def reject(repos: Repos, sug_id: str, actor: str, reason: str | None) -> None:
    sug = await repos.recon.get_suggestion(sug_id)
    if sug is None:
        raise LookupError("suggestion not found")
    if sug["status"] == "approved":
        raise ConflictError("already approved; cannot reject")
    await repos.recon.update_suggestion(sug_id, {"status": "rejected", "rejected_by": actor,
                                                 "reject_reason": reason})
    await repos.recon.set_transaction_status(sug["transaction_id"], "rejected")
    await repos.audit.log(actor, "suggestion_rejected", f"suggestion:{sug_id}", {"reason": reason})


async def approve(repos: Repos, sug_id: str, actor: str, invoice_numbers: list[str] | None,
                  close_with_tds: bool) -> dict:
    """Apply a receipt to invoice(s). Nothing changes unless every check passes.

    * ``invoice_numbers`` overrides the suggestion ("choose a different invoice"). With several
      invoices, each is settled in order (oldest due first) and the receipt must cover them exactly.
    * ``close_with_tds`` settles a shortfall as TDS, only when plausible: INR, and the shortfall equals
      10% of the subtotal (within ₹1).
    """
    sug = await repos.recon.get_suggestion(sug_id)
    if sug is None:
        raise LookupError("suggestion not found")
    tx = await repos.recon.get_transaction(sug["transaction_id"])
    if tx is None:
        raise LookupError("transaction not found")
    if tx["direction"] != "credit":
        raise ReconciliationError("only receipts (credits) can be applied")
    if tx["status"] not in ("suggested", "unmatched", "rejected"):
        raise ConflictError(f"transaction is {tx['status']}; it cannot be applied again")

    numbers = invoice_numbers or [a["invoice_number"] for a in sug.get("allocations", [])]
    if not numbers:
        raise ReconciliationError("choose an invoice to apply this receipt to")
    if len(set(numbers)) != len(numbers):
        raise ReconciliationError("duplicate invoice in selection")
    invoices = []
    for n in numbers:
        inv = await repos.master.get_invoice(n)
        if inv is None:
            raise ReconciliationError(f"{n} not found")
        if inv.status != "sent" or inv.balance_minor <= 0:
            raise ReconciliationError(f"{n} is {inv.status} with balance {inv.balance_minor}; cannot apply")
        if inv.currency != tx["currency"]:
            raise ReconciliationError(f"currency mismatch: receipt is {tx['currency']}, {n} is {inv.currency}")
        invoices.append(inv)
    if len({i.customer_id for i in invoices}) > 1:
        raise ReconciliationError("selected invoices belong to different customers")
    invoices.sort(key=lambda i: (i.due_date, i.invoice_number))

    amount = tx["amount_minor"]
    plan: list[dict] = []
    remaining = amount
    for idx, inv in enumerate(invoices):
        last = idx == len(invoices) - 1
        expected_tds = tds_minor(inv.subtotal_minor) if inv.currency == "INR" and not inv.amount_paid_minor \
            and not inv.tds_minor else 0
        if not last:
            # settle earlier invoices fully (with TDS if the approver chose it and it fits)
            cash = inv.balance_minor - (expected_tds if close_with_tds and expected_tds else 0)
            tds_part = inv.balance_minor - cash
        else:
            cash = remaining
            tds_part = 0
            shortfall = inv.balance_minor - cash
            if cash > inv.balance_minor:
                raise ReconciliationError(
                    f"receipt exceeds what is owed: {format_amount(cash, inv.currency)} vs balance "
                    f"{format_amount(inv.balance_minor, inv.currency)} on {inv.invoice_number}; over-payment is "
                    "not applied automatically")
            if close_with_tds and shortfall > 0:
                if not expected_tds or abs(shortfall - expected_tds) > TDS_TOLERANCE_MINOR:
                    raise ReconciliationError(
                        f"TDS close not plausible for {inv.invoice_number}: shortfall "
                        f"{format_amount(shortfall, inv.currency)}, expected 10% of subtotal = "
                        f"{format_amount(expected_tds, inv.currency) if expected_tds else 'n/a (INR only)'}")
                tds_part = shortfall
        if cash <= 0 or cash > remaining:
            raise ReconciliationError("receipt does not cover the selected invoices")
        remaining -= cash
        plan.append({"invoice": inv, "cash": cash, "tds": tds_part})
    if remaining != 0:
        raise ReconciliationError("receipt is not fully allocated")

    claimed = await repos.recon.claim_transaction_any(tx["_id"])
    if claimed is None:
        raise ConflictError("transaction is already being applied or was applied")
    applied: list[dict] = []
    try:
        for p in plan:
            updated = await repos.master.apply_settlement(p["invoice"].invoice_number, p["cash"], p["tds"])
            if updated is None:
                raise ConflictError(f"{p['invoice'].invoice_number} changed meanwhile (would be over-paid)")
            applied.append({**p, "updated": updated})
    except Exception:
        for a in applied:  # compensate: put balances back exactly
            await repos.master.revert_settlement(a["invoice"].invoice_number, a["cash"], a["tds"])
        await repos.recon.set_transaction_status(tx["_id"], tx["status"])
        raise

    now = clock.now()
    allocations = []
    for a in applied:
        inv, upd = a["invoice"], a["updated"]
        await repos.recon.insert_payment({
            "_id": new_id(), "transaction_id": tx["_id"], "suggestion_id": sug_id, "invoice_number": inv.invoice_number,
            "customer_id": inv.customer_id, "currency": inv.currency, "amount_minor": a["cash"],
            "tds_minor": a["tds"], "txn_date": tx["txn_date"], "reference": tx.get("reference", ""),
            "narration": tx["narration"], "approved_by": actor, "approved_at": now,
        })
        text = f"Payment {format_amount(a['cash'], inv.currency)} received {tx['txn_date']} (ref {tx.get('reference') or '-'})"
        if a["tds"]:
            text += f"; TDS {format_amount(a['tds'], inv.currency)} settled (awaiting TDS certificate)"
        await repos.master.add_invoice_note(inv.invoice_number, {"at": now.isoformat(), "kind": "payment",
                                                                 "text": text})
        allocations.append({"invoice_number": inv.invoice_number, "customer_id": inv.customer_id,
                            "amount_minor": a["cash"], "tds_minor": a["tds"], "new_balance_minor": upd.balance_minor,
                            "new_status": upd.status})
    await repos.recon.set_transaction_status(tx["_id"], "approved")
    await repos.recon.update_suggestion(sug_id, {"status": "approved", "approved_by": actor, "approved_at": now,
                                                 "applied": allocations, "close_with_tds": close_with_tds,
                                                 "overridden": bool(invoice_numbers)})
    await repos.audit.log(actor, "payment_approved", f"transaction:{tx['_id']}",
                          {"amount_minor": amount, "currency": tx["currency"], "allocations": allocations,
                           "suggested": [a["invoice_number"] for a in sug.get("allocations", [])],
                           "close_with_tds": close_with_tds})
    return {"applied": allocations}
