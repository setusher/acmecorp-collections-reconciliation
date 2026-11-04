"""Load data/*.json into MongoDB (idempotent) and reset demo data."""
from __future__ import annotations

import json
from pathlib import Path

from app.core.config import Settings
from app.core.security import normalize_email
from app.models.domain import Customer, Invoice
from app.repositories import Repos

TRANSACTIONAL = ("conversations", "messages", "payments", "bank_statements", "bank_transactions",
                 "match_suggestions")


def parse_email_overrides(raw: str) -> dict[str, str]:
    """``C002=a@x.com,C007=b@y.com`` -> {"C002": "a@x.com", ...} (validated, lowercased)."""
    out: dict[str, str] = {}
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"bad SEED_CUSTOMER_EMAILS entry {part!r}, expected C00X=email")
        cid, email = (x.strip() for x in part.split("=", 1))
        out[cid] = normalize_email(email)
    return out


def load_source(data_dir: Path) -> tuple[dict, list[dict], list[Invoice]]:
    org = json.loads((data_dir / "organization.json").read_text())
    customers = json.loads((data_dir / "customers.json").read_text())
    invoices = [Invoice.from_source(r) for r in json.loads((data_dir / "invoices.json").read_text())]
    return org, customers, invoices


async def seed(repos: Repos, settings: Settings, overwrite: bool = False) -> dict:
    """Insert missing records. ``overwrite=True`` restores the original data exactly."""
    org, customers, invoices = load_source(Path(settings.data_dir))
    if settings.org_email_address:
        org["accounts_email"] = normalize_email(settings.org_email_address)
    overrides = parse_email_overrides(settings.seed_customer_emails)
    unknown = set(overrides) - {c["customer_id"] for c in customers}
    if unknown:
        raise ValueError(f"SEED_CUSTOMER_EMAILS names unknown customers: {sorted(unknown)}")
    await repos.master.upsert_organization(org, overwrite)
    for c in customers:
        doc = Customer(**c).model_dump()
        doc["contact_email"] = normalize_email(doc["contact_email"])
        await repos.master.upsert_customer(doc, overwrite)
    for inv in invoices:
        await repos.master.upsert_invoice(inv, overwrite)
    for cid, email in overrides.items():  # explicit overrides always win
        await repos.master.update_customer(cid, {"contact_email": email})
    return {"organization": 1, "customers": len(customers), "invoices": len(invoices),
            "email_overrides": len(overrides)}


async def reset(repos: Repos, settings: Settings, actor: str) -> dict:
    for name in TRANSACTIONAL:
        await repos.db[name].delete_many({})
    result = await seed(repos, settings, overwrite=True)
    await repos.audit.log(actor, "reset_demo_data", "system", result)
    return result
