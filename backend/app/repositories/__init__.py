from __future__ import annotations

from dataclasses import dataclass

from motor.motor_asyncio import AsyncIOMotorDatabase

from app.repositories.audit_repo import AuditRepo
from app.repositories.collections_repo import CollectionsRepo
from app.repositories.master_data import MasterDataRepo
from app.repositories.reconciliation_repo import ReconciliationRepo


@dataclass
class Repos:
    db: AsyncIOMotorDatabase
    master: MasterDataRepo
    collections: CollectionsRepo
    recon: ReconciliationRepo
    audit: AuditRepo

    @classmethod
    def from_db(cls, db: AsyncIOMotorDatabase) -> "Repos":
        return cls(db, MasterDataRepo(db), CollectionsRepo(db), ReconciliationRepo(db), AuditRepo(db))
