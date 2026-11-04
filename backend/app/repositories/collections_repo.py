"""Conversations and messages."""
from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo.errors import DuplicateKeyError

from app.core import clock
from app.repositories.db import new_id


class CollectionsRepo:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def create_conversation(self, customer_id: str | None, subject: str, status: str = "open") -> dict:
        now = clock.now()
        doc = {"_id": new_id(), "customer_id": customer_id, "subject": subject, "status": status, "notes": [],
               "attention_reason": None, "last_reminder_at": None, "reminder_count": 0,
               "created_at": now, "updated_at": now}
        await self.db.conversations.insert_one(doc)
        return doc

    async def get_conversation(self, conv_id: str) -> dict | None:
        return await self.db.conversations.find_one({"_id": conv_id})

    async def update_conversation(self, conv_id: str, fields: dict[str, Any], push: dict | None = None) -> None:
        upd: dict[str, Any] = {"$set": {**fields, "updated_at": clock.now()}}
        if push:
            upd["$push"] = push
        await self.db.conversations.update_one({"_id": conv_id}, upd)

    async def latest_conversation_for_customer(self, customer_id: str) -> dict | None:
        return await self.db.conversations.find_one({"customer_id": customer_id}, sort=[("updated_at", -1)])

    async def list_conversations(self, status: str | None = None, customer_id: str | None = None,
                                 limit: int = 200) -> list[dict]:
        q: dict[str, Any] = {}
        if status:
            q["status"] = status
        if customer_id:
            q["customer_id"] = customer_id
        return [d async for d in self.db.conversations.find(q).sort("updated_at", -1).limit(limit)]

    async def insert_message(self, doc: dict) -> bool:
        """Insert; False if this Message-ID was already stored (idempotent processing)."""
        doc.setdefault("_id", new_id())
        doc.setdefault("created_at", clock.now())
        try:
            await self.db.messages.insert_one(doc)
            return True
        except DuplicateKeyError:
            return False

    async def message_exists(self, message_id: str) -> bool:
        return await self.db.messages.count_documents({"message_id": message_id}, limit=1) > 0

    async def find_conversation_by_message_ids(self, ids: list[str]) -> str | None:
        if not ids:
            return None
        doc = await self.db.messages.find_one({"message_id": {"$in": [str(i) for i in ids]}},
                                              sort=[("created_at", -1)])
        return doc["conversation_id"] if doc else None

    async def list_messages(self, conv_id: str) -> list[dict]:
        return [d async for d in self.db.messages.find({"conversation_id": conv_id}).sort("created_at", 1)]

    async def update_message(self, msg_id: str, fields: dict[str, Any]) -> None:
        await self.db.messages.update_one({"_id": msg_id}, {"$set": fields})

    async def last_outbound(self, conv_id: str) -> dict | None:
        return await self.db.messages.find_one({"conversation_id": conv_id, "direction": "out"},
                                               sort=[("created_at", -1)])
