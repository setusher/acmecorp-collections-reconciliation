import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("APP_AS_OF_DATE", "2026-11-05")
os.environ.setdefault("LLM_PROVIDER", "none")

DATA = Path(__file__).resolve().parents[2] / "data"


@pytest.fixture(scope="session")
def raw_data():
    return {
        "organization": json.loads((DATA / "organization.json").read_text()),
        "customers": json.loads((DATA / "customers.json").read_text()),
        "invoices": json.loads((DATA / "invoices.json").read_text()),
    }


@pytest.fixture
def invoices(raw_data):
    from app.models.domain import Invoice

    return [Invoice.from_source(r) for r in raw_data["invoices"]]


@pytest.fixture
def customers(raw_data):
    from app.models.domain import Customer

    return [Customer(**c) for c in raw_data["customers"]]


@pytest.fixture
def organization(raw_data):
    from app.models.domain import Organization

    return Organization(**raw_data["organization"])
