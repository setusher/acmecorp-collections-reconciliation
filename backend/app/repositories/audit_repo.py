from __future__ import annotations

from typing import Any

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.core import clock
from app.repositories.db import new_id


class AuditRepo:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.db = db

    async def log(self, actor: str, action: str, entity: str, details: dict[str, Any] | None = None) -> None:
        await self.db.audit_log.insert_one({"_id": new_id(), "at": clock.now(), "actor": actor, "action": action,
                                            "entity": entity, "details": details or {}})

    async def list(self, limit: int = 200) -> list[dict]:
        return [d async for d in self.db.audit_log.find().sort("at", -1).limit(limit)]
