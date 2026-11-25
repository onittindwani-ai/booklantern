"""QuickBooks Online adapter. Tested against a mock written from Intuit's public material, NOT against the real service.

VERIFIED from Intuit's discovery document and SDK readme (2026-11-23): authorization and token endpoints, the accounting scope
com.intuit.quickbooks.accounting, access tokens last 3600 seconds, a sandbox base URL.
UNVERIFIED (Intuit's API pages could not be read when this was built): the paths /v3/company/{realmId}/bill, /invoice and /query, the
`minorversion` query value (a setting), and the field names in the bodies. Read first: only list calls run unless writing is switched on.
"""

from __future__ import annotations

import base64
import time

import httpx

from booklantern.adapters.base import DraftBill, PostedDraft, RemoteInvoice, safe_base_url
from booklantern.money import to_major_number, to_minor
from sendora_core.adapters import AdapterError
from sendora_core.safety import write_action

SANDBOX = "https://sandbox-quickbooks.api.intuit.com"
PRODUCTION = "https://quickbooks.api.intuit.com"


class QuickBooksAccounting:
    def __init__(self, settings, client: httpx.Client | None = None, token_client: httpx.Client | None = None):
        self.settings = settings
        for n in ("qbo_client_id", "qbo_client_secret", "qbo_refresh_token", "qbo_realm_id"):
            if not getattr(settings, n):
                raise AdapterError(f"{n.upper()} is not set. See docs/04-ENVIRONMENT-VARIABLES.md.")
        self.refresh_token = settings.qbo_refresh_token
        self.access = ""
        self.access_until = 0.0
        base = settings.qbo_api_base or (PRODUCTION if settings.qbo_environment == "production" else SANDBOX)
        self.client = client or httpx.Client(base_url=safe_base_url(base), timeout=20)
        self.token_client = token_client or httpx.Client(timeout=20)

    def _token(self) -> str:
        if self.access and time.time() < self.access_until - 60:
            return self.access
        basic = base64.b64encode(f"{self.settings.qbo_client_id}:{self.settings.qbo_client_secret}".encode()).decode()
        r = self.token_client.post(self.settings.qbo_token_url, data={"grant_type": "refresh_token", "refresh_token": self.refresh_token},
                                   headers={"Authorization": f"Basic {basic}", "Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"})
        if r.status_code >= 400:
            raise AdapterError("QuickBooks refused the refresh token. Connect the company again to get a new one.")
        j = r.json()
        self.access = j["access_token"]
        self.refresh_token = j.get("refresh_token", self.refresh_token)  # a new refresh token can come back each time, keep the latest one
        self.access_until = time.time() + int(j.get("expires_in", 3600))
        return self.access

    def _call(self, method: str, path: str, **kw) -> dict:
        url = f"/v3/company/{self.settings.qbo_realm_id}{path}"
        params = {"minorversion": self.settings.qbo_minor_version, **kw.pop("params", {})}
        for attempt in (1, 2):
            r = self.client.request(method, url, params=params, headers={"Authorization": f"Bearer {self._token()}", "Accept": "application/json"}, **kw)
            if r.status_code == 401 and attempt == 1:
                self.access = ""  # the token may have expired early, get a new one once
                continue
            break
        if r.status_code == 401:
            raise AdapterError("QuickBooks rejected the access token twice. Reconnect the company.")
        if r.status_code >= 400:
            msg = ""
            try:
                msg = r.json()["fault"]["error"][0]["message"]
            except Exception:
                msg = str(r.status_code)
            raise AdapterError(f"QuickBooks said: {msg}")
        return r.json()

    def list_open_invoices(self) -> list[RemoteInvoice]:
        j = self._call("GET", "/query", params={"query": "select * from Invoice where Balance > '0'"})
        out = []
        for i in j.get("QueryResponse", {}).get("Invoice", []):
            cur = i.get("CurrencyRef", {}).get("value", "USD")
            out.append(RemoteInvoice(str(i.get("DocNumber", i.get("Id"))), (i.get("CustomerRef") or {}).get("name", ""), to_minor(str(i.get("TotalAmt", 0)), cur), to_minor(str(i.get("Balance", 0)), cur), i.get("DueDate", ""), cur))
        return out

    @write_action("accounting.create_draft_bill")
    def create_draft_bill(self, bill: DraftBill) -> PostedDraft:
        if not self.settings.accounting_write:
            raise AdapterError("ACCOUNTING_WRITE is false, so no bill is posted to QuickBooks. This is the safe default.")
        lines = bill.lines or [{"description": "Bill " + bill.number, "total_minor": bill.subtotal_minor}]  # a bill with no readable lines is still posted, with its subtotal on one line
        body = {"VendorRef": {"name": bill.vendor_name, "value": "0"}, "DocNumber": bill.number, "TxnDate": bill.issue_date, "DueDate": bill.due_date, "PrivateNote": bill.memo, "CurrencyRef": {"value": bill.currency},
                "Line": [{"DetailType": "AccountBasedExpenseLineDetail", "Amount": to_major_number(ln["total_minor"], bill.currency), "Description": ln["description"], "AccountBasedExpenseLineDetail": {"AccountRef": {"value": "0"}}} for ln in lines]}
        if bill.tax_minor:
            body["TxnTaxDetail"] = {"TotalTax": to_major_number(bill.tax_minor, bill.currency)}  # the tax as printed on the bill, so the draft carries the approved total (field name UNVERIFIED)
        params = {"requestid": bill.idempotency_key[:50]} if bill.idempotency_key else {}  # QuickBooks answers a repeated request id with the first result
        made = self._call("POST", "/bill", json=body, params=params)["Bill"]
        returned = made.get("TotalAmt")
        return PostedDraft(str(made["Id"]), to_minor(str(returned), bill.currency) if returned is not None else None, bill.currency)

    def healthcheck(self) -> tuple[bool, str]:
        try:
            self._call("GET", "/query", params={"query": "select * from CompanyInfo"})
            return True, "QuickBooks answered."
        except AdapterError as exc:
            return False, str(exc)
        except httpx.HTTPError as exc:
            return False, f"Could not reach QuickBooks: {type(exc).__name__}."
