"""The data a real install starts with: vendors, customers, open invoices, a bank account, a chart of accounts and repeating items.

Only the owner enters these: a vendor's bank account is the number every payment check is compared with, and customers are the people who get reminders.
Each call is one transaction and is written to the audit log.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from booklantern import setup_data
from booklantern.api.deps import db, get_ctx, owner
from booklantern.context import Ctx
from booklantern.models import Account, BankAccount, Vendor
from sendora_core.audit import record_audit

router = APIRouter(prefix="/api", tags=["setup"])


def _unprocessable(exc: Exception) -> HTTPException:
    return HTTPException(422, str(exc))


class CsvIn(BaseModel):
    text: str = Field(min_length=1, max_length=8_000_000)


class VendorIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    currency: str = Field(default="", max_length=3)
    tax_rate_bp: int = Field(default=0, ge=0, le=10_000)
    requires_po: bool = False
    bank_account: str = Field(default="", max_length=80)
    terms_days: int = Field(default=30, ge=0, le=3650)
    address: str = Field(default="", max_length=240)


class VendorPatch(BaseModel):
    bank_account: str | None = Field(default=None, max_length=80)
    requires_po: bool | None = None
    terms_days: int | None = Field(default=None, ge=0, le=3650)
    tax_rate_bp: int | None = Field(default=None, ge=0, le=10_000)


@router.post("/vendors", summary="Add a vendor (owner only)")
def add_vendor(body: VendorIn, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(owner)):
    try:
        v = setup_data.create_vendor(s, ctx.settings, u["user"], **body.model_dump())
    except setup_data.SetupError as exc:
        raise _unprocessable(exc) from exc
    return {"id": v.id, "key": v.key}


@router.patch("/vendors/{vendor_id}", summary="Change a vendor's bank account on file, purchase order rule, terms or tax rate (owner only)")
def change_vendor(vendor_id: int, body: VendorPatch, s: Session = Depends(db), u: dict = Depends(owner)):
    v = s.get(Vendor, vendor_id)
    if v is None:
        raise HTTPException(404, "No such vendor.")
    changed = body.model_dump(exclude_unset=True)
    for k, val in changed.items():
        if val is not None:
            setattr(v, k, val)
    # the new account is not written into the log, only that it changed: the log is read by more people than the vendor list
    record_audit(s, u["user"], "vendor.changed", f"vendor:{v.id}", {"fields": sorted(changed)})
    return {"ok": True}


@router.post("/vendors/import", summary="Import vendors from CSV text (owner only). Columns: name, currency, tax_rate, requires_po, bank_account, terms_days, address.")
def import_vendors(body: CsvIn, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(owner)):
    try:
        return setup_data.import_vendors(s, ctx.settings, u["user"], body.text).to_dict()
    except setup_data.SetupError as exc:
        raise _unprocessable(exc) from exc


class CustomerIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    email: str = Field(default="", max_length=200)
    timezone: str = Field(default="", max_length=60)
    terms_days: int = Field(default=30, ge=0, le=3650)


@router.post("/customers", summary="Add a customer (owner only)")
def add_customer(body: CustomerIn, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(owner)):
    try:
        c = setup_data.create_customer(s, ctx.settings, u["user"], **body.model_dump())
    except setup_data.SetupError as exc:
        raise _unprocessable(exc) from exc
    return {"id": c.id, "key": c.key}


@router.post("/customers/import", summary="Import customers from CSV text (owner only). Columns: name, email, timezone, terms_days.")
def import_customers(body: CsvIn, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(owner)):
    try:
        return setup_data.import_customers(s, ctx.settings, u["user"], body.text).to_dict()
    except setup_data.SetupError as exc:
        raise _unprocessable(exc) from exc


@router.post("/invoices/import", summary="Import open sales invoices from CSV text (owner only). Columns: number, customer, issue_date, due_date, total, currency, paid.")
def import_invoices(body: CsvIn, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(owner)):
    try:
        return setup_data.import_invoices(s, ctx.settings, u["user"], body.text).to_dict()
    except setup_data.SetupError as exc:
        raise _unprocessable(exc) from exc


class BankAccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    currency: str = Field(default="", max_length=3)
    opening_minor: int = Field(default=0, ge=-(10**12), le=10**12)
    opening_date: date | None = None


@router.get("/bank/accounts", summary="Bank accounts")
def bank_accounts(s: Session = Depends(db)):
    return [{"id": a.id, "name": a.name, "currency": a.currency, "opening_minor": a.opening_minor, "opening_date": a.opening_date.isoformat()} for a in s.scalars(select(BankAccount).order_by(BankAccount.id))]


@router.post("/bank/accounts", summary="Add the bank account the statements belong to (owner only)")
def add_bank_account(body: BankAccountIn, s: Session = Depends(db), ctx: Ctx = Depends(get_ctx), u: dict = Depends(owner)):
    try:
        a = setup_data.create_bank_account(s, ctx.settings, u["user"], **body.model_dump())
    except setup_data.SetupError as exc:
        raise _unprocessable(exc) from exc
    return {"id": a.id}


class AccountIn(BaseModel):
    code: str = Field(min_length=1, max_length=12)
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(pattern="^(asset|liability|income|expense)$")


@router.get("/accounts", summary="Chart of accounts")
def accounts(s: Session = Depends(db)):
    return [{"id": a.id, "code": a.code, "name": a.name, "kind": a.kind} for a in s.scalars(select(Account).order_by(Account.code))]


@router.post("/accounts", summary="Add an account to the chart of accounts (owner only)")
def add_account(body: AccountIn, s: Session = Depends(db), u: dict = Depends(owner)):
    try:
        a = setup_data.create_account(s, u["user"], **body.model_dump())
    except setup_data.SetupError as exc:
        raise _unprocessable(exc) from exc
    return {"id": a.id}


class RecurringIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    direction: str = Field(pattern="^(in|out)$")
    amount_minor: int = Field(gt=0, le=10**12)
    cadence: str = Field(pattern="^(monthly|twice_monthly|weekly)$")
    day: int = Field(default=1, ge=1, le=31)
    match_text: str = Field(default="", max_length=120)


@router.post("/recurring", summary="Add a repeating payment or receipt, such as rent or a retainer (owner only)")
def add_recurring(body: RecurringIn, s: Session = Depends(db), u: dict = Depends(owner)):
    try:
        r = setup_data.create_recurring(s, u["user"], **body.model_dump())
    except setup_data.SetupError as exc:
        raise _unprocessable(exc) from exc
    return {"id": r.id}
