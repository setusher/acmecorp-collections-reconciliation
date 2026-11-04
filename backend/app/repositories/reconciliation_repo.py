"""Bank statements, transactions, suggestions and payments."""
from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument

from app.core import clock


class ReconciliationRepo:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def find_statement_by_sha(self, sha: str) -> dict | None:
        return await self.db.bank_statements.find_one({"sha256": sha})

    async def insert_statement(self, doc: dict) -> None:
        await self.db.bank_statements.insert_one(doc)

    async def list_statements(self) -> list[dict]:
        return [d async for d in self.db.bank_statements.find().sort("uploaded_at", -1)]

    async def get_statement(self, sid: str) -> dict | None:
        return await self.db.bank_statements.find_one({"_id": sid})

    async def existing_by_fingerprint(self, fps: list[str]) -> dict[str, dict]:
        """fingerprint -> {statement_id, row_no} of the original (non-duplicate) row."""
        cur = self.db.bank_transactions.find({"fingerprint": {"$in": fps}},
                                             {"fingerprint": 1, "statement_id": 1, "row_no": 1})
        return {d["fingerprint"]: d async for d in cur}

    async def insert_transactions(self, docs: list[dict]) -> None:
        if docs:
            await self.db.bank_transactions.insert_many(docs, ordered=True)

    async def transactions_for(self, sid: str) -> list[dict]:
        return [d async for d in self.db.bank_transactions.find({"statement_id": sid}).sort("row_no", 1)]

    async def get_transaction(self, tid: str) -> dict | None:
        return await self.db.bank_transactions.find_one({"_id": tid})

    async def claim_transaction_any(self, tid: str) -> dict | None:
        """Atomically move a transaction to 'applying' so it can never be applied twice."""
        return await self.db.bank_transactions.find_one_and_update(
            {"_id": tid, "status": {"$in": ["suggested", "unmatched", "rejected"]}},
            {"$set": {"status": "applying", "updated_at": clock.now()}}, return_document=ReturnDocument.AFTER,
        )

    async def set_transaction_status(self, tid: str, status: str) -> None:
        await self.db.bank_transactions.update_one({"_id": tid}, {"$set": {"status": status,
                                                                           "updated_at": clock.now()}})

    async def insert_suggestions(self, docs: list[dict]) -> None:
        if docs:
            await self.db.match_suggestions.insert_many(docs, ordered=True)

    async def suggestions_for(self, sid: str) -> list[dict]:
        return [d async for d in self.db.match_suggestions.find({"statement_id": sid})]

    async def get_suggestion(self, sug_id: str) -> dict | None:
        return await self.db.match_suggestions.find_one({"_id": sug_id})

    async def update_suggestion(self, sug_id: str, fields: dict[str, Any]) -> None:
        await self.db.match_suggestions.update_one({"_id": sug_id}, {"$set": {**fields, "updated_at": clock.now()}})

    async def insert_payment(self, doc: dict) -> None:
        await self.db.payments.insert_one(doc)

    async def payments_for_invoice(self, number: str) -> list[dict]:
        return [d async for d in self.db.payments.find({"invoice_number": number}).sort("approved_at", 1)]
