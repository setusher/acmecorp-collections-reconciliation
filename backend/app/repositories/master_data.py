"""Organization, customers and invoices."""
from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from app.models.domain import Customer, Invoice, Organization

_NO_ID = {"_id": 0}


class MasterDataRepo:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    # organization -------------------------------------------------------
    async def get_organization(self) -> Organization | None:
        doc = await self.db.organization.find_one({"_id": "org"}, _NO_ID)
        return Organization(**doc) if doc else None

    async def upsert_organization(self, org: dict, overwrite: bool) -> None:
        if overwrite:
            await self.db.organization.replace_one({"_id": "org"}, org, upsert=True)
        else:
            await self.db.organization.update_one({"_id": "org"}, {"$setOnInsert": org}, upsert=True)

    # customers ------------------------------------------------------------
    async def list_customers(self) -> list[Customer]:
        return [Customer(**d) async for d in self.db.customers.find({}, _NO_ID).sort("customer_id", 1)]

    async def get_customer(self, customer_id: str) -> Customer | None:
        doc = await self.db.customers.find_one({"customer_id": customer_id}, _NO_ID)
        return Customer(**doc) if doc else None

    async def find_customer_by_email(self, email: str) -> Customer | None:
        doc = await self.db.customers.find_one({"contact_email": email.lower()}, _NO_ID)
        return Customer(**doc) if doc else None

    async def update_customer(self, customer_id: str, fields: dict[str, Any]) -> Customer | None:
        doc = await self.db.customers.find_one_and_update(
            {"customer_id": customer_id}, {"$set": fields}, projection=_NO_ID, return_document=ReturnDocument.AFTER
        )
        return Customer(**doc) if doc else None

    async def upsert_customer(self, doc: dict, overwrite: bool) -> None:
        q = {"customer_id": doc["customer_id"]}
        if overwrite:
            await self.db.customers.replace_one(q, doc, upsert=True)
        else:
            await self.db.customers.update_one(q, {"$setOnInsert": doc}, upsert=True)

    # invoices ---------------------------------------------------------------
    async def list_invoices(self, customer_id: str | None = None, status: str | None = None) -> list[Invoice]:
        q: dict[str, Any] = {}
        if customer_id:
            q["customer_id"] = customer_id
        if status:
            q["status"] = status
        return [Invoice(**d) async for d in self.db.invoices.find(q, _NO_ID).sort("invoice_number", 1)]

    async def get_invoice(self, number: str) -> Invoice | None:
        doc = await self.db.invoices.find_one({"invoice_number": number}, _NO_ID)
        return Invoice(**doc) if doc else None

    async def open_invoices(self, customer_id: str) -> list[Invoice]:
        cur = self.db.invoices.find({"customer_id": customer_id, "status": "sent", "balance_minor": {"$gt": 0}},
                                    _NO_ID).sort("due_date", 1)
        return [Invoice(**d) async for d in cur]

    async def upsert_invoice(self, inv: Invoice, overwrite: bool) -> None:
        doc = inv.model_dump(mode="json")
        q = {"invoice_number": inv.invoice_number}
        if overwrite:
            await self.db.invoices.replace_one(q, doc, upsert=True)
        else:
            await self.db.invoices.update_one(q, {"$setOnInsert": doc}, upsert=True)

    async def apply_settlement(self, number: str, cash_minor: int, tds_minor: int) -> Invoice | None:
        """Atomically reduce the balance. Fails (returns None) if the invoice is not open or would be over-paid."""
        total = cash_minor + tds_minor
        doc = await self.db.invoices.find_one_and_update(
            {"invoice_number": number, "status": "sent", "balance_minor": {"$gte": total}},
            {"$inc": {"amount_paid_minor": cash_minor, "tds_minor": tds_minor, "balance_minor": -total}},
            projection=_NO_ID, return_document=ReturnDocument.AFTER,
        )
        if doc and doc["balance_minor"] == 0:
            doc = await self.db.invoices.find_one_and_update(
                {"invoice_number": number, "balance_minor": 0}, {"$set": {"status": "paid"}},
                projection=_NO_ID, return_document=ReturnDocument.AFTER,
            )
        return Invoice(**doc) if doc else None

    async def add_invoice_note(self, number: str, note: dict) -> None:
        await self.db.invoices.update_one({"invoice_number": number}, {"$push": {"notes": note}})
