"""Xero, Akaunting, Stripe payment links and the CSV accounting adapter. All tier B except CSV. Xero and Akaunting are written from memory of their public docs (UNVERIFIED)."""

from __future__ import annotations

import base64
import csv
import uuid
from pathlib import Path

import httpx

from booklantern.adapters.base import DraftBill, OutcomeUnknown, PostedDraft, RemoteInvoice, safe_base_url, split_tax
from booklantern.money import parse_amount, to_major_number, to_minor
from booklantern.util import csv_safe
from sendora_core.adapters import AdapterError
from sendora_core.safety import write_action


def _fail(what: str, exc: Exception) -> tuple[bool, str]:
    return False, str(exc) if isinstance(exc, AdapterError) else f"Could not reach {what}: {type(exc).__name__}."


class XeroAccounting:
    carries_idempotency_key = True  # the bill request carries an Idempotency-Key header

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
    def create_draft_bill(self, bill: DraftBill) -> PostedDraft:
        if not self.settings.accounting_write:
            raise AdapterError("ACCOUNTING_WRITE is false, so nothing is posted to Xero.")
        lines = bill.lines or [{"description": "Bill " + bill.number, "quantity": 1, "unit_minor": bill.subtotal_minor, "total_minor": bill.subtotal_minor}]
        tax = split_tax(lines, bill.tax_minor)
        body = {"Type": "ACCPAY", "Status": "DRAFT", "InvoiceNumber": bill.number, "Contact": {"Name": bill.vendor_name}, "Date": bill.issue_date, "DueDate": bill.due_date, "CurrencyCode": bill.currency, "LineAmountTypes": "Exclusive",
                "LineItems": [{"Description": ln["description"], "Quantity": ln["quantity"], "UnitAmount": to_major_number(ln["unit_minor"], bill.currency), "TaxAmount": to_major_number(t, bill.currency)} for ln, t in zip(lines, tax)]}
        headers = {**self._h(), **({"Idempotency-Key": bill.idempotency_key[:128]} if bill.idempotency_key else {})}
        r = self.client.post("/api.xro/2.0/Invoices", headers=headers, json=body)
        if r.status_code >= 400:
            raise AdapterError(f"Xero answered {r.status_code} when creating the draft bill.")
        made = r.json()["Invoices"][0]
        returned = made.get("Total")
        return PostedDraft(str(made["InvoiceID"]), to_minor(str(returned), bill.currency) if returned is not None else None, bill.currency)

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
    def create_draft_bill(self, bill: DraftBill) -> PostedDraft:
        if not self.settings.accounting_write:
            raise AdapterError("ACCOUNTING_WRITE is false, so nothing is posted to Akaunting.")
        lines = bill.lines or [{"description": "Bill " + bill.number, "quantity": 1, "unit_minor": bill.subtotal_minor, "total_minor": bill.subtotal_minor}]
        items = [{"name": ln["description"][:100] or "Item", "quantity": ln["quantity"], "price": to_major_number(ln["unit_minor"], bill.currency)} for ln in lines]
        if bill.tax_minor:  # no tax record is invented: the tax printed on the bill goes in as its own line, so the draft carries the approved total
            items.append({"name": "Tax as printed on the bill", "quantity": 1, "price": to_major_number(bill.tax_minor, bill.currency)})
        r = self.client.post("/api/documents", headers=self._h(), json={"type": "bill", "contact_id": 0, "contact_name": bill.vendor_name, "document_number": bill.number, "issued_at": bill.issue_date, "due_at": bill.due_date,
                                                                          "currency_code": bill.currency, "status": "draft", "items": items})
        if r.status_code >= 500:  # a server error may come after the bill was made, and Akaunting cannot recognise a repeated request
            raise OutcomeUnknown(f"Akaunting answered {r.status_code} when creating the draft bill, so it is not known whether the bill was made.")
        if r.status_code >= 400:
            raise AdapterError(f"Akaunting answered {r.status_code} when creating the draft bill.")
        made = r.json()["data"]
        returned = made.get("amount")
        return PostedDraft(str(made["id"]), to_minor(str(returned), bill.currency) if returned is not None else None, bill.currency)

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
        need = ("Number", "Customer", "Total", "Balance", "Due")
        with p.open(newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            missing = [c for c in need if c not in (reader.fieldnames or [])]
            if missing:
                raise AdapterError(f"invoices.csv has no column {', '.join(missing)}. It needs the columns Number, Customer, Total, Balance, Due (the first line of the file).")
            for n, r in enumerate(reader, start=2):
                if not (r["Total"] or "").strip() or not (r["Balance"] or "").strip():
                    continue  # a row with no amount is not an open invoice
                t, b = parse_amount(r["Total"]), parse_amount(r["Balance"])
                if t is None or b is None:
                    raise AdapterError(f"invoices.csv line {n}: the Total or the Balance is not an amount ({(r['Total'] or '')[:20]!r}, {(r['Balance'] or '')[:20]!r}).")
                if t[0] and b[0]:
                    out.append(RemoteInvoice(r["Number"] or "", r["Customer"] or "", t[0], b[0], r["Due"] or "", t[1]))
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
