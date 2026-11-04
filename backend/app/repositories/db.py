"""Mongo connection and indexes."""
from __future__ import annotations

import uuid

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING

from app.core.config import Settings

COLLECTIONS = ("organization", "customers", "invoices", "conversations", "messages", "payments",
               "bank_statements", "bank_transactions", "match_suggestions", "audit_log")


def new_id() -> str:
    return uuid.uuid4().hex


def connect(settings: Settings) -> tuple[AsyncIOMotorClient, AsyncIOMotorDatabase]:
    client = AsyncIOMotorClient(settings.mongo_uri, tz_aware=True, uuidRepresentation="standard",
                                serverSelectionTimeoutMS=5000)
    return client, client[settings.mongo_db]


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    await db.customers.create_index("customer_id", unique=True)
    await db.customers.create_index("contact_email")
    await db.invoices.create_index("invoice_number", unique=True)
    await db.invoices.create_index([("customer_id", ASCENDING), ("status", ASCENDING)])
    await db.messages.create_index("message_id", unique=True)
    await db.messages.create_index([("conversation_id", ASCENDING), ("created_at", ASCENDING)])
    await db.conversations.create_index([("customer_id", ASCENDING), ("updated_at", DESCENDING)])
    await db.conversations.create_index("status")
    await db.bank_statements.create_index("sha256", unique=True)
    await db.bank_transactions.create_index("fingerprint", unique=True)
    await db.bank_transactions.create_index([("statement_id", ASCENDING), ("row_no", ASCENDING)])
    await db.match_suggestions.create_index("transaction_id", unique=True)
    await db.match_suggestions.create_index("statement_id")
    await db.payments.create_index([("transaction_id", ASCENDING), ("invoice_number", ASCENDING)], unique=True)
    await db.payments.create_index("invoice_number")
    await db.audit_log.create_index([("at", DESCENDING)])
