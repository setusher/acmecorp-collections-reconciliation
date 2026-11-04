"""Seed MongoDB from data/*.json.

Usage (from backend/):
  .venv/bin/python -m scripts.seed           # insert anything missing (safe to re-run)
  .venv/bin/python -m scripts.seed --reset   # restore original data, clear conversations/payments/statements

Optional env overrides: SEED_CUSTOMER_EMAILS="C002=you+kestrel@gmail.com,C007=..." and ORG_EMAIL_ADDRESS.
"""
from __future__ import annotations

import asyncio
import sys

from app.core.config import get_settings
from app.repositories import Repos
from app.repositories.db import connect, ensure_indexes
from app.services.seed_service import reset, seed


async def main(do_reset: bool) -> None:
    settings = get_settings()
    client, db = connect(settings)
    try:
        await ensure_indexes(db)
        repos = Repos.from_db(db)
        result = await (reset(repos, settings, "seed-script") if do_reset else seed(repos, settings))
        print(f"Seeded {settings.mongo_db}: {result}")
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main("--reset" in sys.argv))
