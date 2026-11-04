"""Organization, customers and invoices."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core import clock
from app.core.money import format_amount
from app.core.security import check_customer_id, check_invoice_number, normalize_email
from app.models.domain import Invoice
from app.repositories import Repos
from app.routes.deps import repos, require_user

router = APIRouter(prefix="/api", tags=["master data"], dependencies=[Depends(require_user)])


def invoice_view(inv: Invoice, today: date) -> dict:
    cur = inv.currency
    return {
        **inv.model_dump(mode="json", exclude={"line_items", "notes"}),
        "overdue": inv.is_overdue(today),
        "days_overdue": inv.days_overdue(today),
        "display": {k: format_amount(getattr(inv, f"{k}_minor"), cur)
                    for k in ("subtotal", "discount", "tax", "total", "amount_paid", "tds", "balance")},
    }


@router.get("/organization")
async def get_organization(r: Repos = Depends(repos)) -> dict:
    org = await r.master.get_organization()
    if org is None:
        raise HTTPException(404, "organization not seeded; run the seed script")
    return org.model_dump()


@router.get("/customers")
async def list_customers(r: Repos = Depends(repos)) -> list[dict]:
    today = clock.today()
    invoices = await r.master.list_invoices()
    out = []
    for c in await r.master.list_customers():
        mine = [i for i in invoices if i.customer_id == c.customer_id]
        open_ = [i for i in mine if i.is_open()]
        bal = sum(i.balance_minor for i in open_)
        out.append({**c.model_dump(), "invoice_count": len(mine), "open_count": len(open_),
                    "overdue_count": sum(1 for i in open_ if i.is_overdue(today)),
                    "outstanding_minor": bal, "outstanding_display": format_amount(bal, c.currency)})
    return out


@router.get("/customers/{customer_id}")
async def get_customer(customer_id: str, r: Repos = Depends(repos)) -> dict:
    c = await r.master.get_customer(check_customer_id(customer_id))
    if c is None:
        raise HTTPException(404, "customer not found")
    today = clock.today()
    return {**c.model_dump(), "invoices": [invoice_view(i, today) for i in await r.master.list_invoices(c.customer_id)]}


class CustomerPatch(BaseModel):
    contact_email: str | None = Field(default=None, max_length=254)
    aliases: list[str] | None = Field(default=None, max_length=10)


@router.patch("/customers/{customer_id}")
async def update_customer(customer_id: str, body: CustomerPatch, r: Repos = Depends(repos),
                          user: str = Depends(require_user)) -> dict:
    cid = check_customer_id(customer_id)
    current = await r.master.get_customer(cid)
    if current is None:
        raise HTTPException(404, "customer not found")
    fields: dict = {}
    if body.contact_email is not None:
        email = normalize_email(body.contact_email)
        other = await r.master.find_customer_by_email(email)
        if other and other.customer_id != cid:
            raise HTTPException(409, f"{email} is already the contact for {other.name}")
        org = await r.master.get_organization()
        if org and email == org.accounts_email.lower():
            raise HTTPException(400, "customer email cannot be the organization's own inbox")
        fields["contact_email"] = email
    if body.aliases is not None:
        aliases = [" ".join(a.split())[:100] for a in body.aliases if a and a.strip()]
        fields["aliases"] = aliases
    if not fields:
        raise HTTPException(400, "nothing to update")
    updated = await r.master.update_customer(cid, fields)
    await r.audit.log(user, "customer_updated", f"customer:{cid}",
                      {"from": {"contact_email": current.contact_email, "aliases": current.aliases}, "to": fields})
    return updated.model_dump() if updated else {}


@router.get("/invoices")
async def list_invoices(
    r: Repos = Depends(repos),
    status: str | None = Query(default=None, pattern="^(draft|sent|paid)$"),
    customer_id: str | None = Query(default=None, pattern=r"^C\d{3,5}$"),
    overdue: bool | None = None,
) -> list[dict]:
    today = clock.today()
    out = [invoice_view(i, today) for i in await r.master.list_invoices(customer_id, status)]
    if overdue is not None:
        out = [i for i in out if i["overdue"] == overdue]
    return out


@router.get("/invoices/{number}")
async def get_invoice(number: str, r: Repos = Depends(repos)) -> dict:
    inv = await r.master.get_invoice(check_invoice_number(number))
    if inv is None:
        raise HTTPException(404, "invoice not found")
    payments = await r.recon.payments_for_invoice(inv.invoice_number)
    return {
        **invoice_view(inv, clock.today()),
        "line_items": [{**li.model_dump(), "unit_price_display": format_amount(li.unit_price_minor, inv.currency),
                        "amount_display": format_amount(li.amount_minor, inv.currency)} for li in inv.line_items],
        "notes": [n.model_dump(mode="json") for n in inv.notes],
        "payments": [{"amount_display": format_amount(p["amount_minor"], inv.currency),
                      "tds_display": format_amount(p.get("tds_minor", 0), inv.currency),
                      **{k: v for k, v in p.items() if k != "_id"}} for p in payments],
    }
