"""Xero, Akaunting, Stripe payment links and the CSV accounting adapter. All tier B except CSV. Xero and Akaunting are written from memory of their public docs (UNVERIFIED)."""

from __future__ import annotations

import base64
import csv
import uuid
from pathlib import Path

import httpx

from booklantern.adapters.base import DraftBill, RemoteInvoice, safe_base_url
from booklantern.money import parse_amount, to_major_number, to_minor
from booklantern.util import csv_safe
from sendora_core.adapters import AdapterError
from sendora_core.safety import write_action


def _fail(what: str, exc: Exception) -> tuple[bool, str]:
    return False, str(exc) if isinstance(exc, AdapterError) else f"Could not reach {what}: {type(exc).__name__}."


class XeroAccounting:
    def __init__(self, settings, client: httpx.Client | None = None):
        self.settings = settings
        if not settings.xero_access_token or not settings.xero_tenant_id:
            raise AdapterError("XERO_ACCESS_TOKEN and XERO_TENANT_ID must both be set.")
        self.client = client or httpx.Client(base_url=safe_base_url(settings.xero_base_url), timeout=20)

    def _h(self) -> dict:
        return {"Authorization": f"Bearer {self.settings.xero_access_token}", "xero-tenant-id": self.settings.xero_tenant_id, "Accept": "application/json"}

    def list_open_invoices(self) -> list[RemoteInvoice]:
        r = self.client.get("/api.xro/2.0/Invoices", headers=self._h(), params={"where": 'Type=="ACCREC" AND Status=="AUTHORISED"'})
        if r.status_code >= 400:
            raise AdapterError(f"Xero answered {r.status_code}. Check the access token and tenant id.")
        return [RemoteInvoice(i.get("InvoiceNumber", ""), (i.get("Contact") or {}).get("Name", ""), to_minor(str(i.get("Total", 0)), i.get("CurrencyCode", "USD")), to_minor(str(i.get("AmountDue", 0)), i.get("CurrencyCode", "USD")), str(i.get("DueDate", ""))[:10], i.get("CurrencyCode", "USD")) for i in r.json().get("Invoices", [])]

    @write_action("accounting.create_draft_bill")
    def create_draft_bill(self, bill: DraftBill) -> str:
        if not self.settings.accounting_write:
            raise AdapterError("ACCOUNTING_WRITE is false, so nothing is posted to Xero.")
        body = {"Type": "ACCPAY", "Status": "DRAFT", "InvoiceNumber": bill.number, "Contact": {"Name": bill.vendor_name}, "Date": bill.issue_date, "DueDate": bill.due_date, "CurrencyCode": bill.currency,
                "LineItems": [{"Description": ln["description"], "Quantity": ln["quantity"], "UnitAmount": to_major_number(ln["unit_minor"], bill.currency)} for ln in bill.lines]}
        headers = {**self._h(), **({"Idempotency-Key": bill.idempotency_key[:128]} if bill.idempotency_key else {})}
        r = self.client.post("/api.xro/2.0/Invoices", headers=headers, json=body)
        if r.status_code >= 400:
            raise AdapterError(f"Xero answered {r.status_code} when creating the draft bill.")
        return str(r.json()["Invoices"][0]["InvoiceID"])

    def healthcheck(self) -> tuple[bool, str]:
        try:
            self.list_open_invoices()
            return True, "Xero answered."
        except Exception as exc:
            return _fail("Xero", exc)


class AkauntingAccounting:
    def __init__(self, settings, client: httpx.Client | None = None):
        self.settings = settings
        if not settings.akaunting_base_url or not settings.akaunting_user:
            raise AdapterError("AKAUNTING_BASE_URL and AKAUNTING_USER must both be set.")
        # a self hosted Akaunting is often on a private address, so the guard allows http and local only when the owner chose that URL on purpose
        self.client = client or httpx.Client(base_url=safe_base_url(settings.akaunting_base_url, allow_http_local=True), timeout=20)

    def _h(self) -> dict:
        return {"Authorization": "Basic " + base64.b64encode(f"{self.settings.akaunting_user}:{self.settings.akaunting_password}".encode()).decode(), "Accept": "application/json"}

    def list_open_invoices(self) -> list[RemoteInvoice]:
        r = self.client.get("/api/documents", headers=self._h(), params={"type": "invoice"})
        if r.status_code >= 400:
            raise AdapterError(f"Akaunting answered {r.status_code}. Check the base URL, user and password.")
        return [RemoteInvoice(str(d.get("document_number", d.get("id"))), str((d.get("contact") or {}).get("name", "")), to_minor(str(d.get("amount", 0)), "USD"), to_minor(str(d.get("amount", 0)), "USD"), str(d.get("due_at", ""))[:10]) for d in r.json().get("data", [])]

    @write_action("accounting.create_draft_bill")
    def create_draft_bill(self, bill: DraftBill) -> str:
        if not self.settings.accounting_write:
            raise AdapterError("ACCOUNTING_WRITE is false, so nothing is posted to Akaunting.")
        r = self.client.post("/api/documents", headers=self._h(), json={"type": "bill", "contact_id": 0, "document_number": bill.number, "issued_at": bill.issue_date, "due_at": bill.due_date, "currency_code": bill.currency, "status": "draft"})
        if r.status_code >= 400:
            raise AdapterError(f"Akaunting answered {r.status_code} when creating the draft bill.")
        return str(r.json()["data"]["id"])

    def healthcheck(self) -> tuple[bool, str]:
        try:
            self.list_open_invoices()
            return True, "Akaunting answered."
        except Exception as exc:
            return _fail("Akaunting", exc)


class CsvAccounting:
    """Reads open invoices from invoices.csv (Number, Customer, Total, Balance, Due) in CSV_FOLDER, and writes drafts as a CSV file there. Needs no account at all."""

    def __init__(self, settings):
        self.settings = settings

    def list_open_invoices(self) -> list[RemoteInvoice]:
        p = Path(self.settings.csv_folder) / "invoices.csv"
        if not p.exists():
            raise AdapterError(f"Put an invoices.csv file in {self.settings.csv_folder} with the columns Number, Customer, Total, Balance, Due.")
        out = []
        for r in csv.DictReader(p.open()):
            t, b = parse_amount(r["Total"]), parse_amount(r["Balance"])
            if t and b:
                out.append(RemoteInvoice(r["Number"], r["Customer"], t[0], b[0], r["Due"], t[1]))
        return out

    @write_action("accounting.create_draft_bill")
    def create_draft_bill(self, bill: DraftBill) -> str:
        p = Path(self.settings.csv_folder) / "draft-bills.csv"
        new = not p.exists()
        with p.open("a", newline="") as f:
            w = csv.writer(f)
            if new:
                w.writerow(["Vendor", "Number", "Issued", "Due", "Currency", "Subtotal", "Tax", "Total"])
            w.writerow([csv_safe(v) for v in (bill.vendor_name, bill.number, bill.issue_date, bill.due_date, bill.currency, bill.subtotal_minor, bill.tax_minor, bill.total_minor)])
        return f"csv-row-{bill.number}"

    def healthcheck(self) -> tuple[bool, str]:
        return (True, "The CSV folder is there.") if Path(self.settings.csv_folder).exists() else (False, f"The folder {self.settings.csv_folder} does not exist.")


class StripePayments:
    """Creates a Stripe payment link for an invoice (POST /v1/payment_links, VERIFIED on the API reference page 2026-11-23). A link is a page where the customer pays: this system never charges, captures or moves money."""

    def __init__(self, settings, client: httpx.Client | None = None):
        self.settings = settings
        if not settings.stripe_secret_key:
            raise AdapterError("STRIPE_SECRET_KEY is not set.")
        self.client = client or httpx.Client(base_url=safe_base_url(settings.stripe_base_url), timeout=20)

    @write_action("payments.create_link")
    def create_payment_link(self, *, invoice_number: str, amount_minor: int, currency: str, description: str) -> str:
        form = {"line_items[0][price_data][currency]": currency.lower(), "line_items[0][price_data][unit_amount]": str(amount_minor), "line_items[0][price_data][product_data][name]": description[:200],
                "line_items[0][quantity]": "1", "metadata[invoice]": invoice_number}  # price_data and product_data field names UNVERIFIED on the page read
        r = self.client.post("/v1/payment_links", data=form, auth=(self.settings.stripe_secret_key, ""), headers={"Idempotency-Key": f"ll-{invoice_number}-{amount_minor}"})
        if r.status_code == 401:
            raise AdapterError("Stripe rejected the key. Use a restricted key that can only create payment links.")
        if r.status_code >= 400:
            raise AdapterError(f"Stripe said: {r.json().get('error', {}).get('message', r.status_code)}")
        return r.json()["url"]

    def healthcheck(self) -> tuple[bool, str]:
        return (True, "A key is set. A real check would create a link, so none is made.") if self.settings.stripe_secret_key else (False, "No key.")


def new_idempotency_key() -> str:
    return uuid.uuid4().hex
