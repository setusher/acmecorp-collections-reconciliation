"""Domain models shared by services. Money fields are integer minor units."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.money import to_minor

InvoiceStatus = Literal["draft", "sent", "paid"]
Currency = Literal["INR", "USD", "EUR", "GBP"]


class BankDetails(BaseModel):
    account_name: str
    account_number: str
    bank: str
    ifsc: str | None = None
    swift_code: str | None = None


class Organization(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    address: str
    accounts_contact_name: str
    accounts_email: str
    phone: str
    default_currency: str
    accepted_currencies: list[str]
    payment_terms: str
    payment_methods: list[str]
    bank_details: BankDetails
    policies: dict[str, str]


class Customer(BaseModel):
    model_config = ConfigDict(extra="ignore")
    customer_id: str
    name: str
    contact_name: str
    contact_email: str
    phone: str | None = None
    city: str | None = None
    country: str | None = None
    currency: Currency
    aliases: list[str] = Field(default_factory=list)


class LineItem(BaseModel):
    description: str
    quantity: str  # kept as a decimal string (e.g. "48000", "0.5")
    unit_price_minor: int
    amount_minor: int


class InvoiceNote(BaseModel):
    at: datetime
    kind: str
    text: str


class Invoice(BaseModel):
    model_config = ConfigDict(extra="ignore")
    invoice_number: str
    customer_id: str
    customer_name: str
    po_number: str | None = None
    invoice_date: date
    due_date: date
    payment_terms: str
    currency: Currency
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal_minor: int
    discount_minor: int = 0
    tax_name: str | None = None
    tax_minor: int = 0
    total_minor: int
    amount_paid_minor: int = 0
    tds_minor: int = 0  # amount settled as TDS (withheld by the customer)
    balance_minor: int
    status: InvoiceStatus
    notes: list[InvoiceNote] = Field(default_factory=list)

    @classmethod
    def from_source(cls, raw: dict) -> "Invoice":
        """Build from an ``invoices.json`` record (major units -> minor units)."""
        return cls(
            invoice_number=raw["invoice_number"],
            customer_id=raw["customer_id"],
            customer_name=raw["customer_name"],
            po_number=raw.get("po_number"),
            invoice_date=date.fromisoformat(raw["invoice_date"]),
            due_date=date.fromisoformat(raw["due_date"]),
            payment_terms=raw["payment_terms"],
            currency=raw["currency"],
            line_items=[
                LineItem(
                    description=li["description"],
                    quantity=str(li["quantity"]),
                    unit_price_minor=to_minor(li["unit_price"]),
                    amount_minor=to_minor(li["amount"]),
                )
                for li in raw.get("line_items", [])
            ],
            subtotal_minor=to_minor(raw["subtotal"]),
            discount_minor=to_minor(raw.get("discount", 0)),
            tax_name=raw.get("tax_name"),
            tax_minor=to_minor(raw.get("tax", 0)),
            total_minor=to_minor(raw["total"]),
            amount_paid_minor=to_minor(raw.get("amount_paid", 0)),
            balance_minor=to_minor(raw["balance_due"]),
            status=raw["status"],
        )

    def is_open(self) -> bool:
        """Customer owes money on it: sent (not draft/paid) with a balance."""
        return self.status == "sent" and self.balance_minor > 0

    def is_overdue(self, today: date) -> bool:
        return self.is_open() and self.due_date < today

    def days_overdue(self, today: date) -> int:
        return (today - self.due_date).days if self.is_overdue(today) else 0
